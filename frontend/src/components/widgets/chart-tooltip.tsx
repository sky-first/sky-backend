"use client"

import { cn } from "@/lib/utils"

type AnyPayloadItem = {
  name?: any
  dataKey?: any
  value?: any
  color?: string
  payload?: any
}

export function ChartTooltip({
  active,
  payload,
  label,
  valueFormatter,
}: {
  active?: boolean
  payload?: AnyPayloadItem[]
  label?: any
  valueFormatter?: (value: any) => string
}) {
  if (!active || !payload || payload.length === 0) return null

  const items = payload
    .filter(Boolean)
    .slice(0, 6)
    .map((p) => ({
      name: String(p?.name ?? p?.dataKey ?? p?.payload?.name ?? ""),
      value: p?.value,
      color: p?.color || "#3b82f6",
    }))
    .filter((x) => x.name || x.value != null)

  const title =
    label != null && String(label).trim()
      ? String(label)
      : items[0]?.name
        ? items[0]?.name
        : ""

  const fmt = (v: any) => {
    try {
      return valueFormatter ? valueFormatter(v) : String(v ?? "")
    } catch {
      return String(v ?? "")
    }
  }

  return (
    <div
      className={cn(
        "rounded-xl border bg-white",
        "px-3 py-2",
        "shadow-[0_14px_40px_rgba(15,23,42,0.14)]",
        "min-w-[140px] max-w-[240px]"
      )}
    >
      {title ? (
        <div className="text-[11px] font-semibold text-slate-900 leading-snug mb-1 line-clamp-2">
          {title}
        </div>
      ) : null}

      <div className="space-y-1">
        {items.map((it, idx) => (
          <div key={idx} className="flex items-center justify-between gap-3">
            <div className="min-w-0 flex items-center gap-2">
              <span
                className="h-2 w-2 rounded-full shrink-0"
                style={{ backgroundColor: it.color }}
              />
              <span className="min-w-0 text-[11px] text-slate-600 truncate">
                {it.name || "Value"}
              </span>
            </div>
            <span className="text-[11px] font-semibold text-slate-900 tabular-nums">
              {fmt(it.value)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

