import { Search, X } from "lucide-react";
import type { FormEvent } from "react";

type BookingSearchFormProps = {
  inputId: string;
  value: string;
  placeholder: string;
  disabled?: boolean;
  isActive?: boolean;
  onValueChange: (value: string) => void;
  onSearch: () => void;
  onClear: () => void;
};

function BookingSearchForm({
  inputId,
  value,
  placeholder,
  disabled = false,
  isActive = false,
  onValueChange,
  onSearch,
  onClear
}: BookingSearchFormProps) {
  const hasInput = value.trim().length > 0;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSearch();
  }

  return (
    <form className="bookingSearchForm" onSubmit={handleSubmit}>
      <label htmlFor={inputId}>Booking ID</label>
      <div className="bookingSearchField">
        <Search size={16} />
        <input
          id={inputId}
          type="search"
          value={value}
          placeholder={placeholder}
          disabled={disabled}
          onChange={(event) => onValueChange(event.target.value)}
        />
      </div>
      <button className="bookingSearchButton" type="submit" disabled={disabled || !hasInput}>
        <Search size={15} />
        <span>Search</span>
      </button>
      <button
        className="bookingClearButton"
        type="button"
        disabled={disabled || (!hasInput && !isActive)}
        onClick={onClear}
      >
        <X size={15} />
        <span>Clear</span>
      </button>
    </form>
  );
}

export default BookingSearchForm;
