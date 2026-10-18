-- english-tracker 建表语句。
-- 应用启动时 AUTO_CREATE_TABLES=1 会自动执行等价的 SQL；这份是给控制台
-- 手动建表、或想核对表结构时用的。
-- 库名建议 english_tracker，字符集 utf8mb4。

CREATE TABLE IF NOT EXISTS users (
  id               BIGINT       NOT NULL AUTO_INCREMENT,
  openid           VARCHAR(64)  NOT NULL,
  nickname         VARCHAR(64)  NOT NULL DEFAULT '',
  avatar           VARCHAR(1024) NOT NULL DEFAULT '',
  -- 默认形象（bird/cat/dog/sheep/turtle/whale），建号时随机分配
  animal           VARCHAR(16)  NOT NULL DEFAULT '',
  checkin_reminder TINYINT(1)   NOT NULL DEFAULT 0,
  reminder_time    VARCHAR(5)   NOT NULL DEFAULT '21:00',
  review_reminder  TINYINT(1)   NOT NULL DEFAULT 0,
  created_at       DATETIME     NOT NULL,
  updated_at       DATETIME     NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_openid (openid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS checkins (
  id         BIGINT     NOT NULL AUTO_INCREMENT,
  openid     VARCHAR(64) NOT NULL,
  date       DATE       NOT NULL,
  is_offline TINYINT(1) NOT NULL DEFAULT 0,
  synced     TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME   NOT NULL,
  PRIMARY KEY (id),
  -- 打卡去重靠这个唯一键，而不是"先查再写"
  UNIQUE KEY uq_checkins_openid_date (openid, date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS diaries (
  id         BIGINT       NOT NULL AUTO_INCREMENT,
  openid     VARCHAR(64)  NOT NULL,
  title      VARCHAR(128) NOT NULL DEFAULT '',
  date       DATE         NOT NULL,
  content    TEXT         NOT NULL,
  note       TEXT         NULL,
  word_count INT          NOT NULL DEFAULT 0,
  char_count INT          NOT NULL DEFAULT 0,
  created_at DATETIME     NOT NULL,
  updated_at DATETIME     NOT NULL,
  PRIMARY KEY (id),
  -- 一天可以写多篇，所以 (openid, date) 不是唯一索引
  KEY ix_diaries_openid_date (openid, date),
  KEY ix_diaries_openid_created (openid, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS chunks (
  id         BIGINT       NOT NULL AUTO_INCREMENT,
  openid     VARCHAR(64)  NOT NULL,
  phrase     VARCHAR(255) NOT NULL,
  meaning    VARCHAR(512) NOT NULL DEFAULT '',
  source     VARCHAR(255) NOT NULL DEFAULT '',
  tag        VARCHAR(16)  NOT NULL DEFAULT 'phrasal',
  date       DATE         NOT NULL,
  created_at DATETIME     NOT NULL,
  PRIMARY KEY (id),
  KEY ix_chunks_openid_created (openid, created_at),
  KEY ix_chunks_openid_date (openid, date),
  KEY ix_chunks_openid_tag (openid, tag)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS review_cards (
  id          BIGINT       NOT NULL AUTO_INCREMENT,
  openid      VARCHAR(64)  NOT NULL,
  chunk_id    BIGINT       NOT NULL,
  phrase      VARCHAR(255) NOT NULL DEFAULT '',
  meaning     VARCHAR(512) NOT NULL DEFAULT '',
  repetition  INT          NOT NULL DEFAULT 0,
  `interval`  INT          NOT NULL DEFAULT 1,
  easiness    DECIMAL(4,2) NOT NULL DEFAULT 2.50,
  next_review DATE         NOT NULL,
  last_review DATE         NULL,
  created_at  DATETIME     NOT NULL,
  PRIMARY KEY (id),
  KEY ix_cards_openid_next (openid, next_review),
  CONSTRAINT fk_cards_chunk FOREIGN KEY (chunk_id) REFERENCES chunks (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS recordings (
  id         BIGINT       NOT NULL AUTO_INCREMENT,
  openid     VARCHAR(64)  NOT NULL,
  name       VARCHAR(128) NOT NULL DEFAULT '',
  file_id    VARCHAR(512) NOT NULL,
  duration   INT          NOT NULL DEFAULT 0,
  category   VARCHAR(16)  NOT NULL DEFAULT 'other',
  listened   TINYINT(1)   NOT NULL DEFAULT 0,
  date       DATE         NOT NULL,
  created_at DATETIME     NOT NULL,
  PRIMARY KEY (id),
  KEY ix_rec_openid_created (openid, created_at),
  KEY ix_rec_openid_category (openid, category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
