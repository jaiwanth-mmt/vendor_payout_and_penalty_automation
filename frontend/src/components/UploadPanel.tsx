import { AlertTriangle, CalendarDays, FileSpreadsheet, LoaderCircle, Play, UploadCloud } from "lucide-react";
import type { ChangeEvent, DragEvent, FormEvent } from "react";

type UploadPanelProps = {
  selectedFile: File | null;
  approvalDate: string;
  isProcessing: boolean;
  error: string | null;
  onFileSelect: (file: File | null) => void;
  onApprovalDateChange: (value: string) => void;
  onSubmit: () => void;
};

function UploadPanel({
  selectedFile,
  approvalDate,
  isProcessing,
  error,
  onFileSelect,
  onApprovalDateChange,
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
        <label htmlFor="approvalDate">
          <CalendarDays size={18} />
          <span>Approval date</span>
        </label>
        <input
          id="approvalDate"
          type="date"
          value={approvalDate}
          onChange={(event) => onApprovalDateChange(event.target.value)}
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
