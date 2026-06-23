import { ChevronLeft, ChevronRight, Download, FileSpreadsheet, LoaderCircle, Table2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { fetchFinalOutputPreview } from "../api/jobs";
import type { FinalOutputPreviewResponse, JobResponse } from "../types/jobs";
import BookingSearchForm from "./BookingSearchForm";

type FinalOutputPreviewProps = {
  job: JobResponse | null;
  isComplete: boolean;
  onDownload: () => void;
};

const PAGE_SIZE_OPTIONS = [25, 50, 100];

function renderPreviewValue(value: string | number | null | undefined): string {
  if (value === null || typeof value === "undefined") return "";
  return String(value);
}

function FinalOutputPreview({ job, isComplete, onDownload }: FinalOutputPreviewProps) {
  const [preview, setPreview] = useState<FinalOutputPreviewResponse | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE_OPTIONS[0]);
  const [searchInput, setSearchInput] = useState("");
  const [activeSearch, setActiveSearch] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canPreview = Boolean(isComplete && job?.final_output?.download_ready);
  const columns = preview?.columns ?? job?.final_output?.columns ?? [];
  const rowCount = preview?.row_count ?? job?.final_output?.row_count ?? 0;
  const currentPage = preview?.page ?? page;
  const totalPages = preview?.total_pages ?? 1;
  const firstVisibleRow = rowCount ? (currentPage - 1) * pageSize + 1 : 0;
  const lastVisibleRow = rowCount ? Math.min(currentPage * pageSize, rowCount) : 0;

  const statusText = useMemo(() => {
    if (!job) return "Run a workbook to generate the combined file";
    if (job.status === "failed") return "Final output was not generated";
    if (!isComplete) return "Final output will appear after processing";
    if (activeSearch) return `${rowCount.toLocaleString()} rows matching ${activeSearch}`;
    return `${rowCount.toLocaleString()} rows across ${columns.length} columns`;
  }, [activeSearch, columns.length, isComplete, job, rowCount]);

  useEffect(() => {
    setPreview(null);
    setPage(1);
    setSearchInput("");
    setActiveSearch("");
    setError(null);
  }, [job?.job_id]);

  useEffect(() => {
    if (!job?.job_id || !canPreview) {
      setPreview(null);
      setIsLoading(false);
      return;
    }

    let isCancelled = false;
    setIsLoading(true);
    setError(null);

    fetchFinalOutputPreview(job.job_id, page, pageSize, activeSearch)
      .then((payload) => {
        if (!isCancelled) {
          setPreview(payload);
          if (payload.page !== page) {
            setPage(payload.page);
          }
        }
      })
      .catch((previewError) => {
        if (!isCancelled) {
          setPreview(null);
          setError(previewError instanceof Error ? previewError.message : "Unable to load final output preview");
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
  }, [activeSearch, canPreview, job?.job_id, page, pageSize]);

  function handlePageSizeChange(value: string) {
    setPageSize(Number(value));
    setPage(1);
  }

  function handleSearch() {
    const trimmedSearch = searchInput.trim();
    setSearchInput(trimmedSearch);
    setActiveSearch(trimmedSearch);
    setPage(1);
  }

  function handleClearSearch() {
    setSearchInput("");
    setActiveSearch("");
    setPage(1);
  }

  return (
    <section className="finalOutputSurface">
      <div className="surfaceHeader finalOutputHeader">
        <div className="previewTitle">
          <Table2 size={21} />
          <div>
            <h2>Final output</h2>
            <p>{statusText}</p>
          </div>
        </div>
        <div className="finalOutputActions">
          <BookingSearchForm
            inputId="final-output-booking-search"
            value={searchInput}
            placeholder="Search booking ID"
            disabled={!canPreview}
            isActive={Boolean(activeSearch)}
            onValueChange={setSearchInput}
            onSearch={handleSearch}
            onClear={handleClearSearch}
          />
          {job?.final_output && (
            <span className="previewCount">
              {activeSearch ? `${rowCount.toLocaleString()} matches` : `${job.final_output.row_count.toLocaleString()} rows`}
            </span>
          )}
          <button className="ghostButton finalDownloadButton" type="button" disabled={!canPreview} onClick={onDownload}>
            <Download size={17} />
            <span>Download final XLSX</span>
          </button>
        </div>
      </div>

      <div className="tableFrame finalTableFrame">
        {isLoading ? (
          <div className="tableEmpty">
            <LoaderCircle className="spin" size={30} />
            <span>Loading final output preview</span>
          </div>
        ) : error ? (
          <div className="tableEmpty">
            <FileSpreadsheet size={30} />
            <span>{error}</span>
          </div>
        ) : preview?.rows.length ? (
          <table className="previewTable finalOutputTable">
            <colgroup>
              {columns.map((column) => (
                <col className={column === "message" ? "previewNarrativeColumn" : "previewValueColumn"} key={column} />
              ))}
            </colgroup>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th data-kind={column === "message" ? "narrative" : "value"} key={column}>
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((row, rowIndex) => (
                <tr key={`${row.complaint_against_id ?? "final-row"}-${currentPage}-${rowIndex}`}>
                  {columns.map((column) => {
                    const text = renderPreviewValue(row[column]);
                    return (
                      <td data-kind={column === "message" ? "narrative" : "value"} key={column}>
                        {column === "message" ? (
                          <p className="previewTextCell finalMessageCell">{text}</p>
                        ) : (
                          <span className="previewValueCell" title={text}>
                            {text}
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="tableEmpty">
            <FileSpreadsheet size={30} />
            <span>{activeSearch ? `No final output rows match ${activeSearch}` : "Final output preview will render here"}</span>
          </div>
        )}
      </div>

      <div className="finalPagination" aria-label="Final output pagination">
        <span>
          {rowCount ? `${firstVisibleRow.toLocaleString()}-${lastVisibleRow.toLocaleString()} of ${rowCount.toLocaleString()}` : "0 rows"}
        </span>
        <div className="pageSizeControl">
          <label htmlFor="final-output-page-size">Rows per page</label>
          <select
            id="final-output-page-size"
            value={pageSize}
            disabled={!canPreview}
            onChange={(event) => handlePageSizeChange(event.target.value)}
          >
            {PAGE_SIZE_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>
        <div className="pagerButtons">
          <button
            aria-label="Previous final output page"
            type="button"
            disabled={!canPreview || currentPage <= 1}
            onClick={() => setPage((currentValue) => Math.max(1, currentValue - 1))}
          >
            <ChevronLeft size={16} />
          </button>
          <strong>
            Page {currentPage} of {totalPages}
          </strong>
          <button
            aria-label="Next final output page"
            type="button"
            disabled={!canPreview || currentPage >= totalPages}
            onClick={() => setPage((currentValue) => currentValue + 1)}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
    </section>
  );
}

export default FinalOutputPreview;
