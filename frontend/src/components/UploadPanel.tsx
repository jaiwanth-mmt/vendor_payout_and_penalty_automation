import { AlertTriangle, CalendarDays, FileSpreadsheet, LoaderCircle, Play, UploadCloud } from "lucide-react";
import type { ChangeEvent, DragEvent, FormEvent } from "react";

type UploadPanelProps = {
  selectedFile: File | null;
  startDate: string;
  endDate: string;
  isProcessing: boolean;
  error: string | null;
  onFileSelect: (file: File | null) => void;
  onStartDateChange: (value: string) => void;
  onEndDateChange: (value: string) => void;
  onSubmit: () => void;
};

function UploadPanel({
  selectedFile,
  startDate,
  endDate,
  isProcessing,
  error,
  onFileSelect,
  onStartDateChange,
  onEndDateChange,
  onSubmit
}: UploadPanelProps) {
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    onFileSelect(event.target.files?.[0] ?? null);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    const file = event.dataTransfer.files?.[0];
    if (file) {
      onFileSelect(file);
    }
  }

  return (
    <form className="controlSurface" onSubmit={handleSubmit}>
      <div className="surfaceHeader">
        <FileSpreadsheet size={22} />
        <div>
          <h2>QlikSense input</h2>
          <p>Loss recovery workbook</p>
        </div>
      </div>

      <label
        className="dropZone"
        onDragOver={(event) => event.preventDefault()}
        onDrop={handleDrop}
      >
        <input type="file" accept=".xlsx,.xls" onChange={handleFileChange} />
        <UploadCloud size={30} />
        <span>{selectedFile ? selectedFile.name : "Choose Excel workbook"}</span>
        <strong>{selectedFile ? `${(selectedFile.size / 1024).toFixed(1)} KB` : ".xlsx or .xls"}</strong>
      </label>

      <div className="fieldRow">
        <label htmlFor="startDate">
          <CalendarDays size={18} />
          <span>Approval start</span>
        </label>
        <input
          id="startDate"
          type="date"
          value={startDate}
          onChange={(event) => onStartDateChange(event.target.value)}
        />
      </div>

      <div className="fieldRow">
        <label htmlFor="endDate">
          <CalendarDays size={18} />
          <span>Approval end</span>
        </label>
        <input
          id="endDate"
          type="date"
          value={endDate}
          onChange={(event) => onEndDateChange(event.target.value)}
        />
      </div>

      <button className="primaryButton" type="submit" disabled={isProcessing || !selectedFile}>
        {isProcessing ? <LoaderCircle className="spin" size={18} /> : <Play size={18} />}
        <span>{isProcessing ? "Processing" : "Run automation"}</span>
      </button>

      {error && (
        <div className="inlineAlert" role="alert">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      )}
    </form>
  );
}

export default UploadPanel;
