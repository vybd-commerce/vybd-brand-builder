-- Runs once when the postgres volume is first created.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS brain;
CREATE DATABASE vybd_test OWNER vybd;
\connect vybd_test
CREATE EXTENSION IF NOT EXISTS vector;
