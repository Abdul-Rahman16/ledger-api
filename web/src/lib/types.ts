// Shapes returned by the Ledger API (see api/schemas.py on the server).

export interface TopValue {
    value: string | number | null;
    count: number;
}

export interface ColumnStats {
    min?: number | string | null;
    max?: number | string | null;
    mean?: number | null;
    top_values?: TopValue[];
}

export interface ColumnProfile {
    name: string;
    position: number;
    dtype: string;
    null_pct: number;
    unique_count: number | null;
    stats: ColumnStats | null;
}

export interface DatasetDetail {
    id: string;
    name: string;
    source_type: string;
    original_filename: string;
    status: string;
    row_count: number | null;
    column_count: number | null;
    quality_score: number | null;
    /** UTC timestamp without a zone suffix, for example 2026-11-03T17:14:00.408309 */
    created_at: string;
    columns: ColumnProfile[];
}