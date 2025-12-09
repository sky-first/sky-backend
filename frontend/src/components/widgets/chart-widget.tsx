"use client"

import { 
    ResponsiveContainer, 
    AreaChart, 
    Area, 
    BarChart,
    Bar,
    LineChart,
    Line,
    PieChart,
    Pie,
    Cell,
    ScatterChart,
    Scatter,
    XAxis, 
    YAxis, 
    CartesianGrid, 
    Tooltip,
    Legend
} from "recharts"
import { useTheme } from "next-themes"

const data = [
    { name: 'Jan', value: 4000 },
    { name: 'Feb', value: 3000 },
    { name: 'Mar', value: 2000 },
    { name: 'Apr', value: 2780 },
    { name: 'May', value: 1890 },
    { name: 'Jun', value: 2390 },
    { name: 'Jul', value: 3490 },
]

const pieData = [
    { name: 'Category A', value: 400 },
    { name: 'Category B', value: 300 },
    { name: 'Category C', value: 300 },
    { name: 'Category D', value: 200 },
]

const scatterData = [
    { x: 100, y: 200 },
    { x: 120, y: 100 },
    { x: 170, y: 300 },
    { x: 140, y: 250 },
    { x: 150, y: 400 },
    { x: 110, y: 280 },
]

const COLORS = ['#8884d8', '#82ca9d', '#ffc658', '#ff7300', '#00ff00', '#ff00ff']

interface ChartWidgetProps {
    chartType?: 'bar' | 'pie' | 'line' | 'scatter' | 'area'
    data?: any[]
    labels?: string[]
    series?: number[]
}

export function ChartWidget({ 
    chartType = 'bar',
    data: customData,
    labels,
    series
}: ChartWidgetProps) {
    const { theme } = useTheme()
    const isDark = theme === 'dark'

    // Use custom data if provided, otherwise use default
    const chartData = customData || data
    const chartLabels = labels || chartData.map((d: any) => d.name || d.x)

    const tooltipStyle = {
        backgroundColor: isDark ? "#1f2937" : "#fff",
        border: "none",
        borderRadius: "8px",
        boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)"
    }

    const axisStyle = {
        stroke: isDark ? "#888" : "#666",
        fontSize: 12,
        tickLine: false,
        axisLine: false,
    }

    const renderChart = () => {
        switch (chartType) {
            case 'bar':
                return (
                    <BarChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke={isDark ? "#333" : "#eee"} vertical={false} />
                        <XAxis dataKey="name" {...axisStyle} />
                        <YAxis {...axisStyle} />
                        <Tooltip contentStyle={tooltipStyle} />
                        <Bar dataKey="value" fill="#8884d8" radius={[8, 8, 0, 0]} />
                    </BarChart>
                )

            case 'line':
                return (
                    <LineChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke={isDark ? "#333" : "#eee"} vertical={false} />
                        <XAxis dataKey="name" {...axisStyle} />
                        <YAxis {...axisStyle} />
                        <Tooltip contentStyle={tooltipStyle} />
                        <Line 
                            type="monotone" 
                            dataKey="value" 
                            stroke="#8884d8" 
                            strokeWidth={2}
                            dot={{ fill: "#8884d8", r: 4 }}
                            activeDot={{ r: 6 }}
                        />
                    </LineChart>
                )

            case 'pie':
                return (
                    <PieChart>
                        <Pie
                            data={pieData}
                            cx="50%"
                            cy="50%"
                            labelLine={false}
                            label={({ name, percent }) => `${name}: ${((percent || 0) * 100).toFixed(0)}%`}
                            outerRadius={80}
                            fill="#8884d8"
                            dataKey="value"
                        >
                            {pieData.map((entry, index) => (
                                <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                            ))}
                        </Pie>
                        <Tooltip contentStyle={tooltipStyle} />
                        <Legend />
                    </PieChart>
                )

            case 'scatter':
                return (
                    <ScatterChart margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke={isDark ? "#333" : "#eee"} />
                        <XAxis type="number" dataKey="x" name="X" {...axisStyle} />
                        <YAxis type="number" dataKey="y" name="Y" {...axisStyle} />
                        <Tooltip cursor={{ strokeDasharray: '3 3' }} contentStyle={tooltipStyle} />
                        <Scatter name="Data" data={scatterData} fill="#8884d8" />
                    </ScatterChart>
                )

            case 'area':
            default:
                return (
                    <AreaChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                        <defs>
                            <linearGradient id="colorUv" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="#8884d8" stopOpacity={0.8} />
                                <stop offset="95%" stopColor="#8884d8" stopOpacity={0} />
                            </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke={isDark ? "#333" : "#eee"} vertical={false} />
                        <XAxis dataKey="name" {...axisStyle} />
                        <YAxis {...axisStyle} />
                        <Tooltip contentStyle={tooltipStyle} />
                        <Area
                            type="monotone"
                            dataKey="value"
                            stroke="#8884d8"
                            fillOpacity={1}
                            fill="url(#colorUv)"
                        />
                    </AreaChart>
                )
        }
    }

    return (
        <ResponsiveContainer width="100%" height="100%">
            {renderChart()}
        </ResponsiveContainer>
    )
}
