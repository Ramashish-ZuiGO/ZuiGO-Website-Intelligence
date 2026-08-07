"use client";

import React, { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";

import type { ExplanationContent } from "./explanations";

interface AccessibleExplanationProps {
  title: string;
  content?: ExplanationContent;
  explanation?: string;
  shortTooltip?: string;
  className?: string;
  buttonAriaLabel?: string;
  children?: React.ReactNode;
}

const subscribeToClient = () => () => {};

export function AccessibleExplanation({
  title,
  content,
  explanation,
  shortTooltip,
  className = "",
  buttonAriaLabel,
  children,
}: AccessibleExplanationProps) {
  const [isOpen, setIsOpen] = useState(false);
  const isMounted = useSyncExternalStore(
    subscribeToClient,
    () => true,
    () => false,
  );
  const dialogRef = useRef<HTMLDialogElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const structuredFields: Array<[string, string]> = content
    ? ([
        ["Meaning", content.meaning],
        ["Included", content.included],
        ["Excluded", content.excluded],
        ["Method", content.calculation],
        ["Interpretation", content.interpretation],
        ["Limitation", content.limitation],
        ["Example", content.example],
      ] as Array<[string, string | undefined]>).filter(
        (field): field is [string, string] => Boolean(field[1]),
      )
    : [];

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

  function closeDialog() {
    setIsOpen(false);
  }

  const dialog = (
    <dialog
      ref={dialogRef}
      onCancel={(event) => {
        event.preventDefault();
        closeDialog();
      }}
      onClose={() => {
        setIsOpen(false);
        triggerRef.current?.focus();
      }}
      className="backdrop:bg-gray-900/50 p-0 rounded-lg shadow-xl border-0 w-full max-w-lg m-auto fixed inset-0 z-50 open:animate-in open:fade-in-90"
      aria-labelledby={titleId}
    >
      <div className="flex max-h-[85vh] flex-col">
        <div className="flex items-center justify-between border-b p-4">
          <h2 id={titleId} className="text-lg font-semibold text-gray-900">
            {title}
          </h2>
          <button
            type="button"
            onClick={closeDialog}
            className="rounded text-gray-400 hover:text-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Close"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        <div className="overflow-y-auto p-4">
          <div className="space-y-4 text-sm text-gray-600">
            {structuredFields.length > 0 ? (
              <dl className="space-y-4">
                {structuredFields.map(([label, value]) => (
                  <div key={label}>
                    <dt className="font-semibold text-gray-900">{label}</dt>
                    <dd className="mt-1">{value}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p>{explanation}</p>
            )}
            {content?.detailsLink && (
              <a
                className="inline-block font-semibold text-blue-700 underline focus:outline-none focus:ring-2 focus:ring-blue-500"
                href={content.detailsLink}
                onClick={closeDialog}
              >
                Open related evidence
              </a>
            )}
            {children}
          </div>
        </div>

        <div className="flex justify-end border-t bg-gray-50 p-4">
          <button
            type="button"
            onClick={closeDialog}
            className="rounded border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            Close
          </button>
        </div>
      </div>
    </dialog>
  );

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-label={buttonAriaLabel || `Information about ${title}`}
        title={shortTooltip ?? content?.shortTooltip}
        onClick={(event) => {
          event.stopPropagation();
          setIsOpen(true);
        }}
        className={`inline-flex items-center justify-center rounded-full w-5 h-5 bg-gray-100 hover:bg-gray-200 text-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 ml-1 ${className}`}
      >
        <span className="sr-only">Information</span>
        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <path d="M12 16v-4"></path>
          <path d="M12 8h.01"></path>
        </svg>
      </button>
      {isMounted ? createPortal(dialog, document.body) : null}
    </>
  );
}
