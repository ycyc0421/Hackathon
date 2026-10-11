PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('PENDING','PROCESSING','COMPLETED','PARTIAL','FAILED')),
    destination_country TEXT NOT NULL,
    destination_country_name TEXT,
    trade_mode TEXT,
    declared_currency TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    errors_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS items (
    task_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    description TEXT,
    line_no INTEGER,
    PRIMARY KEY (task_id, item_id),
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS documents (
    file_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL CHECK (file_type IN ('PDF','IMAGE','EDI','OTHER')),
    doc_type TEXT,
    process_status TEXT NOT NULL CHECK (process_status IN ('UPLOADED','PARSING','EXTRACTED','FAILED','UNSUPPORTED')),
    page_count INTEGER,
    error_message TEXT,
    parse_method TEXT CHECK (parse_method IS NULL OR parse_method IN ('TEXT_LAYER','OCR','EDI_PARSE')),
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS extracted_fields (
    field_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    file_id TEXT NOT NULL,
    item_id TEXT,
    line_no INTEGER,
    field_key TEXT NOT NULL,
    label TEXT NOT NULL,
    raw_text TEXT,
    raw_value TEXT,
    normalized_value_json TEXT,
    unit TEXT,
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    status TEXT NOT NULL,
    page INTEGER,
    bbox_json TEXT,
    bbox_unit TEXT,
    FOREIGN KEY (file_id) REFERENCES documents(file_id) ON DELETE CASCADE,
    FOREIGN KEY (task_id, item_id) REFERENCES items(task_id, item_id)
);

CREATE INDEX IF NOT EXISTS idx_extracted_fields_file_key ON extracted_fields(file_id, field_key);
CREATE INDEX IF NOT EXISTS idx_extracted_fields_item_key ON extracted_fields(task_id, item_id, field_key);

CREATE TABLE IF NOT EXISTS comparisons (
    comparison_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    item_id TEXT,
    field_key TEXT NOT NULL,
    label TEXT NOT NULL,
    value_type TEXT NOT NULL,
    unit TEXT,
    status TEXT NOT NULL,
    canonical_value_json TEXT,
    severity TEXT NOT NULL,
    rule_id TEXT,
    note TEXT,
    suggested_action TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
    FOREIGN KEY (task_id, item_id) REFERENCES items(task_id, item_id)
);

CREATE TABLE IF NOT EXISTS comparison_values (
    value_id INTEGER PRIMARY KEY AUTOINCREMENT,
    comparison_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    file_id TEXT NOT NULL,
    item_id TEXT,
    line_no INTEGER,
    file_name TEXT NOT NULL,
    raw_value TEXT,
    normalized_value_json TEXT,
    field_status TEXT NOT NULL,
    page INTEGER,
    bbox_json TEXT,
    FOREIGN KEY (comparison_id) REFERENCES comparisons(comparison_id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES documents(file_id) ON DELETE CASCADE,
    FOREIGN KEY (task_id, item_id) REFERENCES items(task_id, item_id)
);

CREATE TABLE IF NOT EXISTS risks (
    risk_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    item_id TEXT,
    comparison_id TEXT,
    risk_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    destination_country TEXT,
    rule_id TEXT,
    rule_source TEXT,
    suggested_action TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
    FOREIGN KEY (task_id, item_id) REFERENCES items(task_id, item_id),
    FOREIGN KEY (comparison_id) REFERENCES comparisons(comparison_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS risk_fields (
    risk_id TEXT NOT NULL,
    field_key TEXT NOT NULL,
    PRIMARY KEY (risk_id, field_key),
    FOREIGN KEY (risk_id) REFERENCES risks(risk_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS risk_files (
    risk_id TEXT NOT NULL,
    file_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (risk_id, file_id),
    FOREIGN KEY (risk_id) REFERENCES risks(risk_id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES documents(file_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS hs_dictionary (
    hs_code TEXT PRIMARY KEY,
    description TEXT,
    hs_version TEXT,
    country_code TEXT,
    risk_level TEXT,
    source TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS golden_cases (
    case_id TEXT PRIMARY KEY,
    dataset_version TEXT NOT NULL,
    file_set_name TEXT NOT NULL,
    expected_result_json TEXT NOT NULL,
    reviewer TEXT,
    review_status TEXT NOT NULL CHECK (review_status IN ('PENDING','VERIFIED','REJECTED')),
    reviewed_at TEXT
);

PRAGMA user_version = 1;
