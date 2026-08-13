import { ConceptInfoButton } from "@/components/metrics/ConceptInfoButton";

export function SectionHeader({
  title,
  conceptId,
  description,
  number,
  actions,
  id,
}: {
  title: string;
  conceptId?: string;
  description?: string;
  number?: number;
  actions?: React.ReactNode;
  id?: string;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3" id={id}>
      <div>
        <h3 className="flex items-center gap-1.5 text-lg font-bold text-slate-900">
          {number != null && (
            <span className="text-slate-400">{number}.</span>
          )}
          {title}
          {conceptId && (
            <ConceptInfoButton conceptId={conceptId} title={title} />
          )}
        </h3>
        {description && (
          <p className="mt-1 text-sm text-slate-500">{description}</p>
        )}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  );
}
