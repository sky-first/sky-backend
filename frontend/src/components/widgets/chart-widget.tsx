"use client"

import { useMemo } from "react"
import { AreaChart, BarChart, DonutChart, LineChart, ScatterChart } from "@tremor/react"
import {
    ResponsiveContainer,
    BarChart as RBarChart,
    Bar as RBar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip as RTooltip,
    Cell,
} from "recharts"
import { ChartTooltip } from "@/components/widgets/chart-tooltip"

interface ChartWidgetProps {
    chartType?: 'bar' | 'column' | 'pie' | 'line' | 'scatter' | 'area'
    data?: any[]
    labels?: string[]
    series?: number[]
    mapping?: { x?: string; y?: string }
}

export function ChartWidget({ 
    chartType = 'bar',
    data: customData,
    labels,
    series,
    mapping,
}: ChartWidgetProps) {
    const colors = useMemo(
        () => ["blue", "cyan", "violet", "emerald", "amber", "rose"],
        []
    )

    // Blue gradient palette (light -> deep), matching the reference style.
    const blueShades = useMemo(
        () => ["#93c5fd", "#60a5fa", "#3b82f6", "#2563eb", "#1d4ed8", "#1e40af"],
        []
    )

    const hexToRgb = (hex: string) => {
        const raw = hex.replace("#", "").trim()
        const h = raw.length === 3 ? raw.split("").map((c) => c + c).join("") : raw
        const n = parseInt(h, 16)
        const r = (n >> 16) & 255
        const g = (n >> 8) & 255
        const b = n & 255
        return { r, g, b }
    }

    const rgba = (hex: string, a: number) => {
        const { r, g, b } = hexToRgb(hex)
        return `rgba(${r}, ${g}, ${b}, ${a})`
    }

    const formatNumber = (n: number) => {
        // Compact-ish formatting without being too aggressive
        if (!isFinite(n)) return String(n)
        const abs = Math.abs(n)
        if (abs >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`
        if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
        if (abs >= 1_000) return `${(n / 1_000).toFixed(1)}K`
        // preserve small decimals
        if (Math.abs(n) > 0 && Math.abs(n) < 1) return n.toFixed(3)
        return n.toLocaleString()
    }

    const valueFormatter = (value: any) => {
        if (typeof value === "number") return formatNumber(value)
        if (typeof value === "string" && value.trim() && !isNaN(Number(value))) {
            return formatNumber(Number(value))
        }
        return String(value ?? "")
    }

    const chartData = useMemo(() => {
        // If customData is provided and is an array, use it
        if (Array.isArray(customData) && customData.length) return customData
        
        // If labels and series are provided, convert them to chart data format
        if (labels && series && Array.isArray(labels) && Array.isArray(series) && labels.length > 0 && series.length > 0) {
            const maxLength = Math.min(labels.length, series.length)
            return labels.slice(0, maxLength).map((label, index) => ({
                name: String(label),
                value: typeof series[index] === 'number' ? series[index] : Number(series[index]) || 0
            }))
        }
        
        return []
    }, [customData, labels, series])

    const inferred = useMemo(() => {
        const first = chartData?.[0]
        const keys = first && typeof first === "object" ? Object.keys(first) : []

        const xKey =
            mapping?.x ||
            (keys.includes("name") ? "name" : keys.includes("x") ? "x" : keys[0])
        const yKey =
            mapping?.y ||
            (keys.includes("value") ? "value" : keys.includes("y") ? "y" : keys[1])

        // ScatterChart requires a "category" field for coloring/legend.
        // Prefer an existing categorical column; otherwise fall back to xKey.
        const categoryKey =
            keys.includes("category")
                ? "category"
                : keys.includes("group")
                    ? "group"
                    : keys.includes("type")
                        ? "type"
                        : (() => {
                              const candidates = keys.filter((k) => k !== xKey && k !== yKey)
                              const firstStringish = candidates.find((k) => {
                                  const v = (first as any)?.[k]
                                  return typeof v === "string"
                              })
                              return firstStringish || xKey || "category"
                          })()

        return {
            xKey: xKey || "name",
            yKey: yKey || "value",
            categoryKey,
        }
    }, [chartData, mapping?.x, mapping?.y])

    if (!chartData.length) {
        return (
            <div className="w-full h-full flex items-center justify-center text-muted-foreground text-sm">
                No data yet.
            </div>
        )
    }

    const index = inferred.xKey
    const category = inferred.yKey
    const scatterCategory = inferred.categoryKey

    // Normalize type names coming from the AI planner/backend.
    const normalizedType = (chartType === "column" ? "bar" : chartType)

    if (chartType === "pie") {
        return (
            <div className="w-full h-full min-h-[180px] min-w-0 tremor-blue-theme">
                <DonutChart
                    data={chartData}
                    category={category}
                    index={index}
                    // Per-slice blue gradient palette (each slice a different blue).
                    colors={blueShades}
                    valueFormatter={valueFormatter}
                    showAnimation
                    showTooltip
                    customTooltip={(props: any) => (
                        <ChartTooltip {...props} valueFormatter={valueFormatter} />
                    )}
                    className="h-full min-h-[180px]"
                />
            </div>
        )
    }

    if (normalizedType === "scatter") {
        return (
            <div className="w-full h-full min-h-[180px] min-w-0 tremor-blue-theme">
                <ScatterChart
                    data={chartData}
                    x={index}
                    y={category}
                    category={scatterCategory}
                    colors={["blue"]}
                    valueFormatter={{
                        x: valueFormatter,
                        y: valueFormatter,
                    }}
                    showAnimation
                    showTooltip
                    customTooltip={(props: any) => (
                        <ChartTooltip {...props} valueFormatter={valueFormatter} />
                    )}
                    showLegend={false}
                    showGridLines={false}
                    yAxisWidth={72}
                    className="h-full min-h-[180px]"
                />
            </div>
        )
    }

    if (normalizedType === "line") {
        return (
            <div className="w-full h-full min-h-[180px] min-w-0 tremor-blue-theme">
                <LineChart
                    data={chartData}
                    index={index}
                    categories={[category]}
                    colors={["blue"]}
                    valueFormatter={valueFormatter}
                    showLegend={false}
                    showAnimation
                    showGridLines={false}
                    showTooltip
                    customTooltip={(props: any) => (
                        <ChartTooltip {...props} valueFormatter={valueFormatter} />
                    )}
                    curveType="monotone"
                    yAxisWidth={56}
                    padding={{ left: 0, right: 8 }}
                    tickGap={8}
                    className="h-full min-h-[180px]"
                />
            </div>
        )
    }

    if (normalizedType === "area") {
        return (
            <div className="w-full h-full min-h-[180px] min-w-0 tremor-blue-theme">
                <AreaChart
                    data={chartData}
                    index={index}
                    categories={[category]}
                    colors={["blue"]}
                    valueFormatter={valueFormatter}
                    showLegend={false}
                    showAnimation
                    showGradient
                    showGridLines={false}
                    showTooltip
                    customTooltip={(props: any) => (
                        <ChartTooltip {...props} valueFormatter={valueFormatter} />
                    )}
                    curveType="monotone"
                    yAxisWidth={56}
                    padding={{ left: 0, right: 8 }}
                    tickGap={8}
                    className="h-full min-h-[180px]"
                />
            </div>
        )
    }

    // Column/Bar: per-bar blue shades (and subtle vertical gradient inside each bar)
    if (normalizedType === "bar") {
        const gradientIds = chartData.map((_, i) => `bar-blue-grad-${i}`)
        return (
            <div className="w-full h-full min-h-[180px] min-w-0 tremor-blue-theme">
                <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0}>
                    <RBarChart data={chartData} margin={{ top: 8, right: 10, left: 0, bottom: 8 }}>
                        <defs>
                            {chartData.map((_, i) => {
                                const base = blueShades[i % blueShades.length]
                                return (
                                    <linearGradient key={gradientIds[i]} id={gradientIds[i]} x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="0%" stopColor={rgba(base, 0.95)} />
                                        <stop offset="100%" stopColor={rgba(base, 0.65)} />
                                    </linearGradient>
                                )
                            })}
                        </defs>

                        <CartesianGrid vertical={false} stroke="rgba(148,163,184,0.25)" />
                        <XAxis
                            dataKey={index}
                            tick={{ fill: "rgb(100 116 139)", fontSize: 10 }}
                            axisLine={{ stroke: "rgba(148,163,184,0.35)" }}
                            tickLine={false}
                            interval="preserveStartEnd"
                            minTickGap={16}
                        />
                        <YAxis
                            width={56}
                            tick={{ fill: "rgb(100 116 139)", fontSize: 10 }}
                            axisLine={{ stroke: "rgba(148,163,184,0.35)" }}
                            tickLine={false}
                        />
                        <RTooltip
                            cursor={{ fill: "rgba(148,163,184,0.08)" }}
                            content={(props: any) => (
                                <ChartTooltip {...props} valueFormatter={valueFormatter} />
                            )}
                        />

                        <RBar
                            dataKey={category}
                            radius={[10, 10, 6, 6]}
                            maxBarSize={40}
                            isAnimationActive
                        >
                            {chartData.map((_, i) => (
                                <Cell key={`cell-${i}`} fill={`url(#${gradientIds[i]})`} />
                            ))}
                        </RBar>
                    </RBarChart>
                </ResponsiveContainer>
            </div>
        )
    }

    return (
        <div className="w-full h-full tremor-blue-theme">
            <BarChart
                data={chartData}
                index={index}
                categories={[category]}
                colors={["blue"]}
                valueFormatter={valueFormatter}
                showLegend={false}
                showAnimation
                showGridLines={false}
                showTooltip
                customTooltip={(props: any) => (
                    <ChartTooltip {...props} valueFormatter={valueFormatter} />
                )}
                yAxisWidth={56}
                padding={{ left: 0, right: 8 }}
                tickGap={8}
                className="h-full"
            />
        </div>
    )
}
