# -*- coding: utf-8 -*-
from sqlite3 import dbapi2 as sqlite3
from flask import Flask, request, session, g, redirect, url_for, abort, render_template, flash, make_response
from flask.ext.cache import Cache
from contextlib import closing
from math import ceil
from collections import Counter
import time

# configuration
DATABASE = 'images.db'
DEBUG = True
SECRET_KEY = 'development key'
USERNAME = 'admin'
PASSWORD = 'default'
SITE_NAME = 'AmzTop10 Image Site'

cache = Cache(config={'CACHE_TYPE': 'simple'})
app = Flask(__name__)
app.config.from_object(__name__)
cache.init_app(app)


class Pagination(object):
    def __init__(self, page, total_count, per_page=10):
        self.page = page
        self.per_page = per_page
        self.total_count = total_count

    @property
    def pages(self):
        return int(ceil(self.total_count / float(self.per_page)))

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def has_next(self):
        return self.page < self.pages

    def iter_pages(self, left_edge=2, left_current=2,
                   right_current=5, right_edge=2):
        last = 0
        for num in xrange(1, self.pages + 1):
            if num <= left_edge or \
                    (num > self.page - left_current - 1 and \
                             num < self.page + right_current) or \
                            num > self.pages - right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num


def make_dicts(cursor, row):
    return dict((cursor.description[idx][0], value)
                for idx, value in enumerate(row))


def connect_db():
    rv = sqlite3.connect(app.config['DATABASE'])
    rv.row_factory = make_dicts
    return rv


def init_db():
    with closing(connect_db()) as db:
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()


def query_db(query, args=(), one=False):
    print query
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


def pagination_query(page_index, page_size=10, dict={}, like=False):
    total_query = "select count(*) as total from images "
    query = "select * from images "
    if len(dict) > 0:
        total_query += "where 1=1 "
        query += " where 1=1 "
        for k, v in dict.items():
            query += ' and ' + k + (' like "%' if like else ' = "') + v + ('%" ' if like else '" ')
            total_query += ' and ' + k + (' like "%' if like else ' = "') + v + ('%" ' if like else '" ')
    query += 'order by createTime desc limit ? offset ?'
    t = query_db(total_query, one=True)['total']

    # pages = int(ceil(t/float(page_size)))
    pagination = Pagination(page_index, t)
    return (pagination, query_db(query, [page_size, (page_index - 1) * page_size]))


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = connect_db()
    return db


def url_for_other_page(page):
    args = request.view_args.copy()
    args['page'] = page
    return url_for(request.endpoint, **args)


app.jinja_env.globals['url_for_other_page'] = url_for_other_page


def url_for_other_blog(blog_id):
    args = request.view_args.copy()
    args['id'] = blog_id
    return url_for('blog', **args)


app.jinja_env.globals['url_for_other_blog'] = url_for_other_blog


@app.context_processor
@cache.cached(timeout=60 * 60 * 24, key_prefix='pop_tags')
def pop_tags():
    print 'query tags'
    tags = query_db('select tags from images')
    tags_list = []
    for tag in tags:
        tags_list.append(tag['tags'].split(','))

    cnt = Counter()
    for tags in tags_list:
        for tag in tags:
            cnt[tag] += 1

    return dict(c_pop_tags=cnt.most_common(10))


@app.template_filter('strftime')
def strftime(secs, pattern="%B %d, %Y"):
    return time.strftime(pattern, time.gmtime(secs))


@app.teardown_request
def teardown_request(exception):
    g._pop_tags = pop_tags()
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


@app.route('/<type>-<int:id>.html')
def blog(type, id):
    blog = query_db('select * from images where type=? and id=?', [type, id], one=True)
    if not blog:
        abort(404)
    prev = query_db('select id from images where type=? and id < ? order by createTime asc limit 1', [type, id],
                    one=True)
    next = query_db('select id from images where type=? and id > ? order by createTime desc  limit 1', [type, id],
                    one=True)
    return render_template('blog.html', blog=blog, type=type, prev=prev, next=next)


@app.route('/<type>/', defaults={'page': 1})
@app.route('/<type>/page/<int:page>')
@cache.cached(60 * 60)
def type(type, page):
    if page <= 0: page = 1
    pagination, results = pagination_query(page, dict={'type': type}, like=True)
    if not results:
        abort(404)
    return render_template('index.html', type=type, results=results, pagination=pagination)


@app.route('/tag/<tag_name>/', defaults={'page': 1})
@app.route('/tag/<tag_name>/page/<int:page>')
@cache.cached(60 * 60)
def tag(tag_name, page):
    if page <= 0: page = 1
    pagination, results = pagination_query(page, dict={'tags': tag_name}, like=True)
    if not results:
        abort(404)
    return render_template('index.html', tag_name=tag_name, results=results, pagination=pagination)


@app.route('/', defaults={'page': 1})
@app.route('/page/<int:page>')
@cache.cached(60 * 60)
def index(page):
    if page <= 0: page = 1
    pagination, results = pagination_query(page)
    return render_template('index.html', results=results, pagination=pagination)


@app.errorhandler(404)
@cache.cached(60 * 60)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def error_server(e):
    return render_template('500.html'), 500


@app.route('/sitemap.xml')
@cache.cached(60 * 60)
def generate_sitemap():
    blogs = query_db('select * from images order by createTime desc  limit 50000')

    pages = []
    for blog in blogs:
        url = url_for('blog', type=blog['type'], id=blog['id'])
        modified_time = time.strftime('%Y-%m-%dT%H:%M:%S+08:00', time.gmtime(blog['createTime']))
        pages.append([url, modified_time])
    sitemap_xml = render_template('sitemap.xml', pages=pages)
    response = make_response(sitemap_xml)
    response.headers["Content-Type"] = "application/xml"
    return response


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7005)
    pass