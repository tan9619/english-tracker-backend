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
  -- 内置语块是否已复制到该用户名下
  presets_seeded   TINYINT(1)   NOT NULL DEFAULT 0,
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
  id               BIGINT       NOT NULL AUTO_INCREMENT,
  openid           VARCHAR(64)  NOT NULL,
  phrase           VARCHAR(255) NOT NULL,
  meaning          VARCHAR(512) NOT NULL DEFAULT '',
  scenario         VARCHAR(128) NOT NULL DEFAULT '',
  example_sentence TEXT         NULL,
  note             TEXT         NULL,
  source           VARCHAR(255) NOT NULL DEFAULT '',
  tag              VARCHAR(16)  NOT NULL DEFAULT 'phrasal',
  -- 掌握状态：learning 待复习 / mastered 已掌握，由复习流程更新
  mastery_status   VARCHAR(16)  NOT NULL DEFAULT 'learning',
  date             DATE         NOT NULL,
  created_at       DATETIME     NOT NULL,
  updated_at       DATETIME     NULL,
  PRIMARY KEY (id),
  KEY ix_chunks_openid_created (openid, created_at),
  KEY ix_chunks_openid_date (openid, date),
  KEY ix_chunks_openid_tag (openid, tag),
  KEY ix_chunks_openid_mastery (openid, mastery_status)
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

-- 复习行为流水：每次提交结果写一条，不覆盖历史。
-- 统计「今日已复习」时按不同 chunk_id 去重。
CREATE TABLE IF NOT EXISTS review_records (
  id          BIGINT      NOT NULL AUTO_INCREMENT,
  openid      VARCHAR(64) NOT NULL,
  chunk_id    BIGINT      NOT NULL,
  review_date DATE        NOT NULL,
  result      VARCHAR(16) NOT NULL,        -- again | mastered
  created_at  DATETIME    NOT NULL,
  PRIMARY KEY (id),
  KEY ix_records_openid_date (openid, review_date),
  KEY ix_records_openid_chunk (openid, chunk_id),
  CONSTRAINT fk_records_chunk FOREIGN KEY (chunk_id) REFERENCES chunks (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS recordings (
  id            BIGINT       NOT NULL AUTO_INCREMENT,
  openid        VARCHAR(64)  NOT NULL,
  title         VARCHAR(128) NOT NULL DEFAULT '',
  practice_type VARCHAR(16)  NOT NULL DEFAULT 'free',   -- free | topic
  topic         VARCHAR(64)  NOT NULL DEFAULT '',
  file_id       VARCHAR(512) NOT NULL,
  duration      INT          NOT NULL DEFAULT 0,
  listened      TINYINT(1)   NOT NULL DEFAULT 0,
  date          DATE         NOT NULL,                   -- recording_date，统计口径
  created_at    DATETIME     NOT NULL,
  updated_at    DATETIME     NULL,
  -- 旧字段，只读兼容
  name          VARCHAR(128) NOT NULL DEFAULT '',
  category      VARCHAR(16)  NOT NULL DEFAULT 'other',
  PRIMARY KEY (id),
  KEY ix_rec_openid_created (openid, created_at),
  KEY ix_rec_openid_date (openid, date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
