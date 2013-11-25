drop table if exists images;

create table images (
  id integer primary key autoincrement,
  title text,
  content text not null,
  type integer,
  tags text,
  isTumblr integer not null default 0,
  postId text not null,
  createTime integer not null
);

