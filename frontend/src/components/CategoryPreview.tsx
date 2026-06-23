import { ChevronDown, ChevronUp, Columns3, FileSpreadsheet, ListCollapse, LoaderCircle, Table2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { fetchCategoryPreview } from "../api/jobs";
import type { CategoryOutput, CategoryPreviewResponse, JobResponse } from "../types/jobs";
import BookingSearchForm from "./BookingSearchForm";
import PaginationControls from "./PaginationControls";

type CategoryPreviewProps = {
  job: JobResponse | null;
  isComplete: boolean;
};

const KEY_PREVIEW_COLUMNS = ["Booking ID", "Sub Category", "Recoverable", "Remarks", "Comments", "message"];
const NARRATIVE_COLUMN_MARKERS = ["comment", "insight", "message", "remark", "summary"];
const EXPANDABLE_TEXT_LENGTH = 150;
const CATEGORY_PAGE_SIZE = 5;

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
  const [categoryPages, setCategoryPages] = useState<Record<string, number>>({});
  const [searchInput, setSearchInput] = useState("");
  const [activeSearch, setActiveSearch] = useState("");
  const [preview, setPreview] = useState<CategoryPreviewResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeCategory = useMemo<CategoryOutput | null>(() => {
    if (!categories.length) return null;
    return categories.find((category) => category.slug === activeSlug) ?? categories[0];
  }, [activeSlug, categories]);

  const activeCategorySlug = activeCategory?.slug ?? "";
  const activePage = activeCategorySlug ? categoryPages[activeCategorySlug] ?? 1 : 1;
  const previewColumns = preview?.columns ?? activeCategory?.output_columns ?? [];
  const previewRows = preview?.rows ?? [];
  const rowCount = preview?.row_count ?? activeCategory?.row_count ?? 0;
  const totalPages = preview?.total_pages ?? Math.max(1, Math.ceil(rowCount / CATEGORY_PAGE_SIZE));

  const keyPreviewColumns = useMemo(() => resolveKeyPreviewColumns(previewColumns), [previewColumns]);

  const isFullColumnMode = showAllColumns || !keyPreviewColumns.length;

  const visibleColumns = useMemo(() => {
    if (!activeCategory) return [];
    if (isFullColumnMode) return previewColumns;
    return keyPreviewColumns;
  }, [activeCategory, isFullColumnMode, keyPreviewColumns, previewColumns]);

  const hasHiddenColumns = Boolean(
    activeCategory && keyPreviewColumns.length > 0 && previewColumns.length > keyPreviewColumns.length
  );

  useEffect(() => {
    setActiveSlug(null);
    setExpandedCell(null);
    setShowAllColumns(false);
    setCategoryPages({});
    setSearchInput("");
    setActiveSearch("");
    setPreview(null);
    setError(null);
  }, [job?.job_id]);

  useEffect(() => {
    if (!categories.length) {
      setActiveSlug(null);
      setExpandedCell(null);
      setShowAllColumns(false);
      setSearchInput("");
      setActiveSearch("");
      setPreview(null);
      setError(null);
      return;
    }

    if (activeSlug && !categories.some((category) => category.slug === activeSlug)) {
      setActiveSlug(null);
      setExpandedCell(null);
      setShowAllColumns(false);
      setSearchInput("");
      setActiveSearch("");
      setPreview(null);
      setError(null);
    }
  }, [activeSlug, categories]);

  useEffect(() => {
    if (!job?.job_id || !isComplete || !activeCategorySlug) {
      setPreview(null);
      setIsLoading(false);
      return;
    }

    let isCancelled = false;
    setIsLoading(true);
    setPreview(null);
    setError(null);

    fetchCategoryPreview(job.job_id, activeCategorySlug, activePage, activeSearch)
      .then((payload) => {
        if (!isCancelled) {
          setPreview(payload);
          if (payload.page !== activePage) {
            setCategoryPages((currentValue) => ({ ...currentValue, [activeCategorySlug]: payload.page }));
          }
        }
      })
      .catch((previewError) => {
        if (!isCancelled) {
          setPreview(null);
          setError(previewError instanceof Error ? previewError.message : "Unable to load category preview");
        }
      })
      .finally(() => {
        if (!isCancelled) {
          setIsLoading(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [activeCategorySlug, activePage, activeSearch, isComplete, job?.job_id]);

  function handleCategorySelect(slug: string) {
    setActiveSlug(slug);
    setExpandedCell(null);
    setShowAllColumns(false);
    setSearchInput("");
    setActiveSearch("");
  }

  function handleColumnModeToggle() {
    setExpandedCell(null);
    setShowAllColumns((currentValue) => !currentValue);
  }

  function handlePageChange(nextPage: number) {
    if (!activeCategorySlug) return;
    setExpandedCell(null);
    setCategoryPages((currentValue) => ({ ...currentValue, [activeCategorySlug]: nextPage }));
  }

  function handleSearch() {
    if (!activeCategorySlug) return;
    const trimmedSearch = searchInput.trim();
    setSearchInput(trimmedSearch);
    setActiveSearch(trimmedSearch);
    setExpandedCell(null);
    setCategoryPages((currentValue) => ({ ...currentValue, [activeCategorySlug]: 1 }));
  }

  function handleClearSearch() {
    if (!activeCategorySlug) return;
    setSearchInput("");
    setActiveSearch("");
    setExpandedCell(null);
    setCategoryPages((currentValue) => ({ ...currentValue, [activeCategorySlug]: 1 }));
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
            <BookingSearchForm
              inputId="category-booking-search"
              value={searchInput}
              placeholder="Search booking ID"
              disabled={!isComplete}
              isActive={Boolean(activeSearch)}
              onValueChange={setSearchInput}
              onSearch={handleSearch}
              onClear={handleClearSearch}
            />
            <span className="previewCount">
              {activeSearch ? `${rowCount.toLocaleString()} matches` : `${activeCategory.row_count} rows`}
            </span>
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
        {isLoading ? (
          <div className="tableEmpty">
            <LoaderCircle className="spin" size={30} />
            <span>Loading category preview</span>
          </div>
        ) : error ? (
          <div className="tableEmpty">
            <FileSpreadsheet size={30} />
            <span>{error}</span>
          </div>
        ) : previewRows.length ? (
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
              {previewRows.map((row, rowIndex) => {
                const rowKey = `${row["Booking ID"] ?? activeCategorySlug}-${preview?.page ?? activePage}-${rowIndex}`;

                return (
                  <tr key={rowKey}>
                    {visibleColumns.map((column) => {
                      const text = renderPreviewValue(row[column]);
                      const isNarrative = isNarrativeColumn(column);
                      const cellKey = `${activeCategorySlug}-${preview?.page ?? activePage}-${rowIndex}-${column}`;
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
            <span>{activeSearch ? `No category rows match ${activeSearch}` : "Processed category rows will render here"}</span>
          </div>
        )}
      </div>

      {activeCategory && (
        <PaginationControls
          label="Category preview pagination"
          page={preview?.page ?? activePage}
          totalPages={totalPages}
          itemCount={rowCount}
          pageSize={CATEGORY_PAGE_SIZE}
          noun="rows"
          disabled={!isComplete || isLoading}
          onPageChange={handlePageChange}
        />
      )}
    </section>
  );
}

export default CategoryPreview;
