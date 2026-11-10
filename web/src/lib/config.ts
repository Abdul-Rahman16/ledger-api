// Limits and copy shared by the UI. Keep them in sync with the API where noted.

/** Vercel functions accept request bodies up to 4.5 MB, and every upload passes through one. */
export const MAX_UPLOAD_BYTES = 4 * 1024 * 1024;

export const ACCEPTED_EXTENSIONS = [".csv", ".xlsx", ".json"] as const;

/** Same limits as the API's ingestion module. */
export const MAX_ROWS = 100_000;
export const MAX_COLUMNS = 100;

/** The API deletes guest datasets after this long (GUEST_RETENTION_HOURS on the server). */
export const GUEST_RETENTION_HOURS = 24;

/**
 * Whether the API reports column null_pct as a fraction (0 to 1) instead of a percentage (0 to 100).
 * The API field is named null_pct, so a percentage is assumed. Flip this if a dataset with blank cells
 * shows values like 0.17 instead of 16.7.
 */
export const NULL_PCT_IS_FRACTION = false;

export const SAMPLE_DATASETS = [
    {
        id: "orders",
        url: "/samples/orders.csv",
        fileName: "orders_sample.csv",
        label: "Sample orders",
        description: "32 orders across 4 regions and 3 products",
    },
    {
        id: "gaps",
        url: "/samples/orders_with_gaps.csv",
        fileName: "orders_with_gaps.csv",
        label: "Sample with gaps",
        description: "Missing values and a constant column, to see the quality checks",
    },
] as const;