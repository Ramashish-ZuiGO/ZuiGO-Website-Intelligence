"use client";

import React from "react";

interface SectionErrorBoundaryProps {
  sectionName: string;
  children: React.ReactNode;
}

interface SectionErrorBoundaryState {
  error: Error | null;
}

export class SectionErrorBoundary extends React.Component<
  SectionErrorBoundaryProps,
  SectionErrorBoundaryState
> {
  constructor(props: SectionErrorBoundaryProps) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): SectionErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    console.error(
      `[SectionErrorBoundary] ${this.props.sectionName}:`,
      error,
      info.componentStack,
    );
  }

  render(): React.ReactNode {
    if (this.state.error) {
      return (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm">
          <p className="font-semibold text-amber-800">
            Unable to display this section because its retained data is
            incomplete.
          </p>
          <p className="mt-1 text-amber-700">
            Section: {this.props.sectionName}
          </p>
          <details className="mt-2">
            <summary className="cursor-pointer text-xs text-amber-600">
              Technical details
            </summary>
            <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-xs text-amber-600">
              {this.state.error.message}
            </pre>
          </details>
        </div>
      );
    }
    return this.props.children;
  }
}
