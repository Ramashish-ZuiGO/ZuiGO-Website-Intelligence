"use client";

import { useState } from "react";

export function UrlCell({
  url,
  maxDisplay = 60,
}: {
  url: string;
  maxDisplay?: number;
}) {
  const [copied, setCopied] = useState(false);
  const isLink = url.startsWith("http://") || url.startsWith("https://");
  const display =
    url.length > maxDisplay ? url.slice(0, maxDisplay - 1) + "…" : url;

  const handleCopy = () => {
    void navigator.clipboard.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    });
  };

  return (
    <span className="group inline-flex min-w-0 max-w-full items-center gap-1">
      {isLink ? (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="min-w-0 truncate text-blue-600 hover:underline"
          title={url}
        >
          {display}
        </a>
      ) : (
        <span className="min-w-0 truncate" title={url}>
          {display}
        </span>
      )}
      <button
        type="button"
        onClick={handleCopy}
        className="shrink-0 rounded p-0.5 text-slate-400 opacity-0 transition-opacity hover:text-slate-600 group-hover:opacity-100"
        title="Copy URL"
        aria-label="Copy URL"
      >
        {copied ? (
          <svg
            className="h-3.5 w-3.5"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M5 13l4 4L19 7"
            />
          </svg>
        ) : (
          <svg
            className="h-3.5 w-3.5"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
            <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
          </svg>
        )}
      </button>
    </span>
  );
}
