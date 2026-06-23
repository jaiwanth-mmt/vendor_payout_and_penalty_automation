import { ChevronDown, ChevronUp, Columns3, FileSpreadsheet, ListCollapse, Table2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { CategoryOutput, JobResponse } from "../types/jobs";

type CategoryPreviewProps = {
  job: JobResponse | null;
  isComplete: boolean;
};

const KEY_PREVIEW_COLUMNS = ["Booking ID", "Sub Category", "Recoverable", "Remarks", "Comments", "message"];
const NARRATIVE_COLUMN_MARKERS = ["comment", "insight", "message", "remark", "summary"];
const EXPANDABLE_TEXT_LENGTH = 150;

function isNarrativeColumn(column: string): boolean {
  const normalizedColumn = column.toLowerCase();
  return NARRATIVE_COLUMN_MARKERS.some((marker) => normalizedColumn.includes(marker));
}

function normalizeColumnName(column: string): string {
  return column.trim().toLowerCase();
}

function resolveKeyPreviewColumns(outputColumns: string[]): string[] {
  const columnsByName = new Map<string, string>();
  outputColumns.forEach((column) => {
    const normalizedColumn = normalizeColumnName(column);
    if (!columnsByName.has(normalizedColumn)) {
      columnsByName.set(normalizedColumn, column);
    }
  });

  return KEY_PREVIEW_COLUMNS.map((column) => columnsByName.get(normalizeColumnName(column))).filter(
    (column): column is string => Boolean(column)
  );
}

function renderPreviewValue(value: string | number | null | undefined): string {
  if (value === null || typeof value === "undefined") return "";
  return String(value);
}

function CategoryPreview({ job, isComplete }: CategoryPreviewProps) {
  const categories = useMemo(() => job?.category_outputs ?? [], [job?.category_outputs]);
  const [activeSlug, setActiveSlug] = useState<string | null>(null);
  const [expandedCell, setExpandedCell] = useState<string | null>(null);
  const [showAllColumns, setShowAllColumns] = useState(false);

  const activeCategory = useMemo<CategoryOutput | null>(() => {
    if (!categories.length) return null;
    return categories.find((category) => category.slug === activeSlug) ?? categories[0];
  }, [activeSlug, categories]);

  const keyPreviewColumns = useMemo(
    () => (activeCategory ? resolveKeyPreviewColumns(activeCategory.output_columns) : []),
    [activeCategory]
  );

  const isFullColumnMode = showAllColumns || !keyPreviewColumns.length;

  const visibleColumns = useMemo(() => {
    if (!activeCategory) return [];
    if (isFullColumnMode) return activeCategory.output_columns;
    return keyPreviewColumns;
  }, [activeCategory, isFullColumnMode, keyPreviewColumns]);

  const hasHiddenColumns = Boolean(
    activeCategory && keyPreviewColumns.length > 0 && activeCategory.output_columns.length > keyPreviewColumns.length
  );

  useEffect(() => {
    setActiveSlug(null);
    setExpandedCell(null);
    setShowAllColumns(false);
  }, [job?.job_id]);

  useEffect(() => {
    if (!categories.length) {
      setActiveSlug(null);
      setExpandedCell(null);
      setShowAllColumns(false);
      return;
    }

    if (activeSlug && !categories.some((category) => category.slug === activeSlug)) {
      setActiveSlug(null);
      setExpandedCell(null);
      setShowAllColumns(false);
    }
  }, [activeSlug, categories]);

  function handleCategorySelect(slug: string) {
    setActiveSlug(slug);
    setExpandedCell(null);
    setShowAllColumns(false);
  }

  function handleColumnModeToggle() {
    setExpandedCell(null);
    setShowAllColumns((currentValue) => !currentValue);
  }

  return (
    <section className="previewSurface">
      <div className="surfaceHeader previewHeader">
        <div className="previewTitle">
          <Table2 size={21} />
          <div>
            <h2>Category preview</h2>
            <p>{isComplete ? `${categories.length} processed category files` : "No package yet"}</p>
          </div>
        </div>
        {activeCategory && (
          <div className="previewActions">
            <span className="previewCount">{activeCategory.row_count} rows</span>
            <button
              aria-expanded={showAllColumns}
              className="previewColumnToggle"
              data-active={showAllColumns}
              disabled={!hasHiddenColumns}
              onClick={handleColumnModeToggle}
              type="button"
            >
              {showAllColumns ? <ListCollapse size={16} /> : <Columns3 size={16} />}
              <span>{showAllColumns ? "Show key columns" : "Show all columns"}</span>
            </button>
          </div>
        )}
      </div>

      {categories.length > 0 && (
        <div className="categoryTabs" role="tablist" aria-label="Processed subcategories">
          {categories.map((category) => (
            <button
              aria-selected={activeCategory?.slug === category.slug}
              className="categoryTab"
              data-active={activeCategory?.slug === category.slug}
              key={category.slug}
              onClick={() => handleCategorySelect(category.slug)}
              role="tab"
              type="button"
            >
              <span>{category.name}</span>
              <strong>{category.row_count}</strong>
            </button>
          ))}
        </div>
      )}

      <div className="tableFrame">
        {activeCategory?.preview_rows.length ? (
          <table className="previewTable" data-mode={isFullColumnMode ? "all" : "key"}>
            <colgroup>
              {visibleColumns.map((column) => (
                <col
                  className={isNarrativeColumn(column) ? "previewNarrativeColumn" : "previewValueColumn"}
                  key={column}
                />
              ))}
            </colgroup>
            <thead>
              <tr>
                {visibleColumns.map((column) => (
                  <th data-kind={isNarrativeColumn(column) ? "narrative" : "value"} key={column}>
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {activeCategory.preview_rows.map((row, rowIndex) => {
                const rowKey = `${row["Booking ID"] ?? activeCategory.slug}-${rowIndex}`;

                return (
                  <tr key={rowKey}>
                    {visibleColumns.map((column) => {
                      const text = renderPreviewValue(row[column]);
                      const isNarrative = isNarrativeColumn(column);
                      const cellKey = `${activeCategory.slug}-${rowIndex}-${column}`;
                      const isExpanded = expandedCell === cellKey;
                      const canExpand = isNarrative && text.length > EXPANDABLE_TEXT_LENGTH;

                      return (
                        <td data-kind={isNarrative ? "narrative" : "value"} key={column}>
                          {isNarrative ? (
                            <div className="previewTextWrap" data-expanded={isExpanded}>
                              <p className="previewTextCell">{text}</p>
                              {canExpand && (
                                <button
                                  aria-expanded={isExpanded}
                                  aria-label={`${isExpanded ? "Collapse" : "Expand"} ${column} for row ${
                                    rowIndex + 1
                                  }`}
                                  className="previewTextToggle"
                                  onClick={() => setExpandedCell(isExpanded ? null : cellKey)}
                                  type="button"
                                >
                                  {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                                  <span>{isExpanded ? "Less" : "More"}</span>
                                </button>
                              )}
                            </div>
                          ) : (
                            <span className="previewValueCell" title={text}>
                              {text}
                            </span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <div className="tableEmpty">
            <FileSpreadsheet size={30} />
            <span>Processed category rows will render here</span>
          </div>
        )}
      </div>
    </section>
  );
}

export default CategoryPreview;
