"use client";

import React, { useRef, useEffect, useState } from "react";

interface AccessibleExplanationProps {
  title: string;
  explanation: string;
  className?: string;
  buttonAriaLabel?: string;
  children?: React.ReactNode;
}

export function AccessibleExplanation({
  title,
  explanation,
  className = "",
  buttonAriaLabel,
  children,
}: AccessibleExplanationProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (isOpen && dialog && !dialog.open) {
      dialog.showModal();
    } else if (!isOpen && dialog && dialog.open) {
      dialog.close();
    }
  }, [isOpen]);

  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  return (
    <>
      <button
        type="button"
        aria-label={buttonAriaLabel || `Information about ${title}`}
        onClick={() => setIsOpen(true)}
        className={`inline-flex items-center justify-center rounded-full w-5 h-5 bg-gray-100 hover:bg-gray-200 text-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 ml-1 ${className}`}
      >
        <span className="sr-only">Information</span>
        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <path d="M12 16v-4"></path>
          <path d="M12 8h.01"></path>
        </svg>
      </button>

      <dialog
        ref={dialogRef}
        onClose={() => setIsOpen(false)}
        className="backdrop:bg-gray-900/50 p-0 rounded-lg shadow-xl border-0 w-full max-w-lg m-auto fixed inset-0 z-50 open:animate-in open:fade-in-90"
        aria-labelledby={`dialog-title-${title.replace(/\s+/g, "-")}`}
      >
        <div className="flex flex-col max-h-[85vh]">
          <div className="flex items-center justify-between p-4 border-b">
            <h2 id={`dialog-title-${title.replace(/\s+/g, "-")}`} className="text-lg font-semibold text-gray-900">
              {title}
            </h2>
            <button
              type="button"
              onClick={() => setIsOpen(false)}
              className="text-gray-400 hover:text-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 rounded"
              aria-label="Close"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
            </button>
          </div>

          <div className="p-4 overflow-y-auto">
            <div className="space-y-4 text-sm text-gray-600">
              <p>{explanation}</p>
              {children}
            </div>
          </div>

          <div className="p-4 border-t bg-gray-50 flex justify-end">
            <button
              type="button"
              onClick={() => setIsOpen(false)}
              className="px-4 py-2 bg-white border border-gray-300 rounded text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              Close
            </button>
          </div>
        </div>
      </dialog>
    </>
  );
}
