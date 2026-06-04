// TODO: Visual search button — triggers image upload for visual similarity search
// Sits inside SearchBar. On image select, calls POST /chat with multipart/form-data.
import { useRef } from "react";

interface Props {
  onImageSelected: (file: File) => void;
  disabled?: boolean;
}

export default function VisualSearchButton({ onImageSelected, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <>
      <button
        type="button"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        title="Search by image"
      >
        {/* Camera icon placeholder */}
        📷
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        style={{ display: "none" }}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onImageSelected(file);
          e.target.value = "";
        }}
      />
    </>
  );
}
