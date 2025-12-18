"use client"

import { useState, useMemo, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { 
    X, Search, Info, 
    BarChart3, TrendingUp, Target, GitBranch, Layout, Sparkles,
    DollarSign, Users, MapPin, TrendingDown, PieChart, Activity,
    Briefcase, Globe, Zap, LineChart, Calendar, Award, AlertCircle
} from "lucide-react"
import { useTemplatesStore } from "@/store/templates-store"
import { useWidgetStore } from "@/store/widget-store"
import { useCanvasStore } from "@/store/canvas-store"
import { useDashboardStore } from "@/store/dashboard-store"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Checkbox } from "@/components/ui/checkbox"
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select"
import { cn } from "@/lib/utils"
import { useTheme } from "next-themes"
import type { Widget } from "@/store/widget-store"
import type { Template as ApiTemplate } from "@/lib/api/templates"

// Local template interface for UI (with icon component and optional fields for hardcoded templates)
interface Template extends Omit<ApiTemplate, 'icon' | 'created_at' | 'updated_at' | 'popular' | 'enterprise'> {
    icon?: React.ElementType
    created_at?: string // Optional for hardcoded templates
    updated_at?: string // Optional for hardcoded templates
    popular?: boolean // Optional for hardcoded templates
    enterprise?: boolean // Optional for hardcoded templates
    question?: string // Optional question for hardcoded templates
    color?: string // Optional color for hardcoded templates
    widgets?: any[] // Optional widgets for hardcoded templates
}

// Templates Empresariais Premium - Melhorados com Best Practices de BI
const TEMPLATES: Template[] = [
    {
        id: '1',
        name: 'Executive Performance Dashboard',
        category: 'all',
        description: 'Comprehensive monthly business performance with trend analysis and key metrics',
        question: 'Como está o desempenho mensal da empresa?',
        icon: Calendar,
        color: 'blue',
        popular: true,
        enterprise: true,
        widgets: [
            // Top Row - Primary KPIs (Hero Metrics)
            {
                type: 'kpi',
                title: 'Monthly Revenue',
                position: { x: 100, y: 80 },
                size: { width: 260, height: 160 },
                data: { value: '$0', change: '0%', label: 'vs last month', trend: 'up' }
            },
            {
                type: 'kpi',
                title: 'Growth Rate',
                position: { x: 380, y: 80 },
                size: { width: 260, height: 160 },
                data: { value: '0%', change: '0%', label: 'MoM growth', trend: 'neutral' }
            },
            {
                type: 'kpi',
                title: 'Active Customers',
                position: { x: 660, y: 80 },
                size: { width: 260, height: 160 },
                data: { value: '0', change: '0%', label: 'total active', trend: 'up' }
            },
            {
                type: 'kpi',
                title: 'Customer Satisfaction',
                position: { x: 940, y: 80 },
                size: { width: 260, height: 160 },
                data: { value: '0%', change: '0%', label: 'NPS score', trend: 'neutral' }
            },
            // Main Chart - Full Width
            {
                type: 'chart',
                title: '12-Month Revenue Trend',
                position: { x: 100, y: 260 },
                size: { width: 1100, height: 380 },
                data: { 
                    type: 'line', 
                    series: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], 
                    labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
                    showGrid: true,
                    showLegend: true
                }
            },
            // Secondary Metrics Row
            {
                type: 'chart',
                title: 'Revenue by Category',
                position: { x: 100, y: 660 },
                size: { width: 540, height: 320 },
                data: { type: 'bar', series: [0, 0, 0, 0, 0], labels: ['Product A', 'Product B', 'Product C', 'Product D', 'Product E'] }
            },
            {
                type: 'table',
                title: 'Top Performing Products',
                position: { x: 660, y: 660 },
                size: { width: 540, height: 320 },
                data: { value: '0', change: '0%', columns: ['Product', 'Revenue', 'Growth', 'Margin'] }
            },
        ]
    },
    {
        id: '2',
        name: 'Product Profitability Analysis',
        category: 'all',
        description: 'Deep dive into product performance, margins, and revenue contribution',
        question: 'Quais produtos estão gerando mais lucro?',
        icon: Briefcase,
        color: 'green',
        popular: true,
        enterprise: true,
        widgets: [
            // Summary KPIs
            {
                type: 'kpi',
                title: 'Total Product Revenue',
                position: { x: 100, y: 80 },
                size: { width: 280, height: 140 },
                data: { value: '$0', change: '0%', label: 'all products' }
            },
            {
                type: 'kpi',
                title: 'Average Margin',
                position: { x: 400, y: 80 },
                size: { width: 280, height: 140 },
                data: { value: '0%', change: '0%', label: 'profit margin' }
            },
            {
                type: 'kpi',
                title: 'Top Product',
                position: { x: 700, y: 80 },
                size: { width: 280, height: 140 },
                data: { value: 'N/A', change: '0%', label: 'by revenue' }
            },
            {
                type: 'kpi',
                title: 'Product Count',
                position: { x: 1000, y: 80 },
                size: { width: 200, height: 140 },
                data: { value: '0', change: '0%', label: 'active products' }
            },
            // Main Visualizations
            {
                type: 'chart',
                title: 'Revenue by Product',
                position: { x: 100, y: 240 },
                size: { width: 700, height: 420 },
                data: { 
                    type: 'bar', 
                    series: [0, 0, 0, 0, 0], 
                    labels: ['Product A', 'Product B', 'Product C', 'Product D', 'Product E'],
                    horizontal: false,
                    showValues: true
                }
            },
            {
                type: 'chart',
                title: 'Profit Margin Distribution',
                position: { x: 820, y: 240 },
                size: { width: 380, height: 420 },
                data: { 
                    type: 'pie', 
                    series: [0, 0, 0, 0, 0],
                    labels: ['High', 'Medium', 'Low', 'Negative', 'Other'],
                    showLegend: true
                }
            },
            // Detailed Table
            {
                type: 'table',
                title: 'Product Performance Matrix',
                position: { x: 100, y: 680 },
                size: { width: 1100, height: 300 },
                data: { 
                    value: '0', 
                    change: '0%',
                    columns: ['Product', 'Revenue', 'Cost', 'Margin %', 'Units Sold', 'Growth'],
                    sortable: true
                }
            },
        ]
    },
    {
        id: '3',
        name: 'Regional Growth Analysis',
        category: 'strategy',
        description: 'Geographic performance analysis with market penetration and growth opportunities',
        question: 'Quais regiões têm maior potencial de crescimento?',
        icon: MapPin,
        color: 'purple',
        popular: true,
        enterprise: true,
        widgets: [
            // Regional KPIs
            {
                type: 'kpi',
                title: 'Top Region',
                position: { x: 100, y: 80 },
                size: { width: 240, height: 140 },
                data: { value: 'N/A', change: '0%', label: 'by revenue' }
            },
            {
                type: 'kpi',
                title: 'Fastest Growth',
                position: { x: 360, y: 80 },
                size: { width: 240, height: 140 },
                data: { value: 'N/A', change: '0%', label: 'YoY growth' }
            },
            {
                type: 'kpi',
                title: 'Market Penetration',
                position: { x: 620, y: 80 },
                size: { width: 240, height: 140 },
                data: { value: '0%', change: '0%', label: 'average' }
            },
            {
                type: 'kpi',
                title: 'Total Regions',
                position: { x: 880, y: 80 },
                size: { width: 240, height: 140 },
                data: { value: '0', change: '0%', label: 'active markets' }
            },
            {
                type: 'kpi',
                title: 'Regional Revenue',
                position: { x: 1140, y: 80 },
                size: { width: 200, height: 140 },
                data: { value: '$0', change: '0%', label: 'total' }
            },
            // Main Map/Chart
            {
                type: 'chart',
                title: 'Regional Performance Heatmap',
                position: { x: 100, y: 240 },
                size: { width: 800, height: 480 },
                data: { 
                    type: 'area', 
                    series: [0, 0, 0, 0, 0, 0],
                    labels: ['North', 'South', 'East', 'West', 'Central', 'International'],
                    stacked: true
                }
            },
            // Regional Breakdown
            {
                type: 'table',
                title: 'Regional Performance Breakdown',
                position: { x: 920, y: 240 },
                size: { width: 420, height: 480 },
                data: { 
                    value: '0', 
                    change: '0%',
                    columns: ['Region', 'Revenue', 'Growth', 'Market Share', 'Rank'],
                    sortable: true
                }
            },
            // Trend Analysis
            {
                type: 'chart',
                title: 'Regional Growth Trends',
                position: { x: 100, y: 740 },
                size: { width: 1240, height: 300 },
                data: { 
                    type: 'line', 
                    series: [0, 0, 0, 0, 0, 0],
                    labels: ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6'],
                    multiSeries: true,
                    showLegend: true
                }
            },
        ]
    },
    {
        id: '4',
        name: 'Customer Acquisition Metrics',
        category: 'all',
        description: 'Comprehensive CAC analysis with channel optimization and LTV insights',
        question: 'Qual é o nosso custo de aquisição de clientes?',
        icon: Users,
        color: 'orange',
        enterprise: true,
        widgets: [
            // Primary Metrics
            {
                type: 'kpi',
                title: 'Average CAC',
                position: { x: 100, y: 80 },
                size: { width: 280, height: 160 },
                data: { value: '$0', change: '0%', label: 'per customer', trend: 'down' }
            },
            {
                type: 'kpi',
                title: 'CAC Payback Period',
                position: { x: 400, y: 80 },
                size: { width: 280, height: 160 },
                data: { value: '0 days', change: '0%', label: 'recovery time', trend: 'down' }
            },
            {
                type: 'kpi',
                title: 'LTV:CAC Ratio',
                position: { x: 700, y: 80 },
                size: { width: 280, height: 160 },
                data: { value: '0:1', change: '0%', label: 'lifetime value', trend: 'up' }
            },
            {
                type: 'kpi',
                title: 'New Customers',
                position: { x: 1000, y: 80 },
                size: { width: 240, height: 160 },
                data: { value: '0', change: '0%', label: 'this month' }
            },
            // Channel Analysis
            {
                type: 'chart',
                title: 'CAC by Acquisition Channel',
                position: { x: 100, y: 260 },
                size: { width: 700, height: 400 },
                data: { 
                    type: 'bar', 
                    series: [0, 0, 0, 0, 0], 
                    labels: ['Organic', 'Paid Ads', 'Social Media', 'Email', 'Referral'],
                    showValues: true,
                    colorByValue: true
                }
            },
            // Channel Efficiency
            {
                type: 'chart',
                title: 'Channel Efficiency Score',
                position: { x: 820, y: 260 },
                size: { width: 420, height: 400 },
                data: { 
                    type: 'pie', 
                    series: [0, 0, 0, 0, 0],
                    labels: ['High', 'Medium', 'Low', 'Poor', 'Other'],
                    showLegend: true
                }
            },
            // Detailed Table
            {
                type: 'table',
                title: 'Channel Performance Matrix',
                position: { x: 100, y: 680 },
                size: { width: 1140, height: 300 },
                data: { 
                    value: '0', 
                    change: '0%',
                    columns: ['Channel', 'CAC', 'Customers', 'LTV', 'ROI', 'Efficiency'],
                    sortable: true
                }
            },
        ]
    },
    {
        id: '5',
        name: 'Marketing ROI Dashboard',
        category: 'all',
        description: 'Comprehensive campaign ROI analysis with channel attribution and optimization',
        question: 'Qual é o ROI das campanhas?',
        icon: Award,
        color: 'indigo',
        popular: true,
        enterprise: true,
        widgets: [
            // ROI Summary
            {
                type: 'kpi',
                title: 'Overall ROI',
                position: { x: 100, y: 80 },
                size: { width: 300, height: 160 },
                data: { value: '0%', change: '0%', label: 'all campaigns', trend: 'up' }
            },
            {
                type: 'kpi',
                title: 'Best Performing',
                position: { x: 420, y: 80 },
                size: { width: 300, height: 160 },
                data: { value: 'N/A', change: '0%', label: 'top campaign' }
            },
            {
                type: 'kpi',
                title: 'Total Investment',
                position: { x: 740, y: 80 },
                size: { width: 300, height: 160 },
                data: { value: '$0', change: '0%', label: 'campaign budget' }
            },
            {
                type: 'kpi',
                title: 'Total Return',
                position: { x: 1060, y: 80 },
                size: { width: 240, height: 160 },
                data: { value: '$0', change: '0%', label: 'revenue generated' }
            },
            // Main Visualization
            {
                type: 'chart',
                title: 'ROI by Campaign',
                position: { x: 100, y: 260 },
                size: { width: 800, height: 420 },
                data: { 
                    type: 'bar', 
                    series: [0, 0, 0, 0, 0],
                    labels: ['Campaign A', 'Campaign B', 'Campaign C', 'Campaign D', 'Campaign E'],
                    showValues: true,
                    colorByValue: true
                }
            },
            // Campaign Details
            {
                type: 'table',
                title: 'Campaign Performance Details',
                position: { x: 920, y: 260 },
                size: { width: 380, height: 420 },
                data: { 
                    value: '0', 
                    change: '0%',
                    columns: ['Campaign', 'ROI', 'Spend', 'Revenue'],
                    sortable: true
                }
            },
            // Trend Analysis
            {
                type: 'chart',
                title: 'ROI Trend Over Time',
                position: { x: 100, y: 700 },
                size: { width: 1200, height: 320 },
                data: { 
                    type: 'line', 
                    series: [0, 0, 0, 0, 0, 0],
                    labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
                    showGrid: true,
                    showLegend: true
                }
            },
        ]
    },
    {
        id: '6',
        name: 'Financial Health Monitor',
        category: 'strategy',
        description: 'Comprehensive financial health indicators with cash flow and profitability analysis',
        question: 'Como está a saúde financeira geral?',
        icon: DollarSign,
        color: 'teal',
        enterprise: true,
        widgets: [
            // Financial KPIs - Top Row
            {
                type: 'kpi',
                title: 'Operating Cash Flow',
                position: { x: 100, y: 80 },
                size: { width: 240, height: 140 },
                data: { value: '$0', change: '0%', label: 'monthly', trend: 'up' }
            },
            {
                type: 'kpi',
                title: 'EBITDA Margin',
                position: { x: 360, y: 80 },
                size: { width: 240, height: 140 },
                data: { value: '0%', change: '0%', label: 'profitability', trend: 'neutral' }
            },
            {
                type: 'kpi',
                title: 'Debt-to-Equity',
                position: { x: 620, y: 80 },
                size: { width: 240, height: 140 },
                data: { value: '0%', change: '0%', label: 'leverage ratio', trend: 'down' }
            },
            {
                type: 'kpi',
                title: 'Quick Ratio',
                position: { x: 880, y: 80 },
                size: { width: 240, height: 140 },
                data: { value: '0:1', change: '0%', label: 'liquidity', trend: 'up' }
            },
            {
                type: 'kpi',
                title: 'Current Ratio',
                position: { x: 1140, y: 80 },
                size: { width: 200, height: 140 },
                data: { value: '0:1', change: '0%', label: 'solvency' }
            },
            // Main Financial Trends
            {
                type: 'chart',
                title: 'Financial Performance Trends',
                position: { x: 100, y: 240 },
                size: { width: 1240, height: 420 },
                data: { 
                    type: 'line', 
                    series: [0, 0, 0, 0, 0, 0],
                    labels: ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6'],
                    multiSeries: true,
                    seriesLabels: ['Revenue', 'Expenses', 'Profit'],
                    showLegend: true,
                    showGrid: true
                }
            },
            // Profitability Breakdown
            {
                type: 'chart',
                title: 'Profitability by Segment',
                position: { x: 100, y: 680 },
                size: { width: 600, height: 300 },
                data: { 
                    type: 'bar', 
                    series: [0, 0, 0, 0],
                    labels: ['Product', 'Service', 'Subscription', 'Other'],
                    horizontal: false
                }
            },
            // Financial Summary Table
            {
                type: 'table',
                title: 'Financial Metrics Summary',
                position: { x: 720, y: 680 },
                size: { width: 620, height: 300 },
                data: { 
                    value: '0', 
                    change: '0%',
                    columns: ['Metric', 'Current', 'Previous', 'Change', 'Status'],
                    sortable: true
                }
            },
        ]
    },
    {
        id: '7',
        name: 'Customer Retention Analytics',
        category: 'all',
        description: 'Advanced churn analysis with cohort retention and lifetime value insights',
        question: 'Qual é a análise de churn?',
        icon: TrendingDown,
        color: 'red',
        enterprise: true,
        widgets: [
            // Churn Metrics
            {
                type: 'kpi',
                title: 'Monthly Churn Rate',
                position: { x: 100, y: 80 },
                size: { width: 280, height: 160 },
                data: { value: '0%', change: '0%', label: 'customers lost', trend: 'down' }
            },
            {
                type: 'kpi',
                title: 'Retention Rate',
                position: { x: 400, y: 80 },
                size: { width: 280, height: 160 },
                data: { value: '0%', change: '0%', label: 'customers retained', trend: 'up' }
            },
            {
                type: 'kpi',
                title: 'Avg Customer Lifetime',
                position: { x: 700, y: 80 },
                size: { width: 280, height: 160 },
                data: { value: '0 months', change: '0%', label: 'CLV', trend: 'up' }
            },
            {
                type: 'kpi',
                title: 'Churned Revenue',
                position: { x: 1000, y: 80 },
                size: { width: 240, height: 160 },
                data: { value: '$0', change: '0%', label: 'MRR lost' }
            },
            // Churn Trend
            {
                type: 'chart',
                title: 'Churn Rate Trend',
                position: { x: 100, y: 260 },
                size: { width: 700, height: 400 },
                data: { 
                    type: 'line', 
                    series: [0, 0, 0, 0, 0, 0],
                    labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
                    showGrid: true,
                    showTarget: true,
                    targetValue: 5
                }
            },
            // Cohort Analysis
            {
                type: 'chart',
                title: 'Cohort Retention Matrix',
                position: { x: 820, y: 260 },
                size: { width: 420, height: 400 },
                data: { 
                    type: 'bar', 
                    series: [0, 0, 0, 0, 0],
                    labels: ['Cohort 1', 'Cohort 2', 'Cohort 3', 'Cohort 4', 'Cohort 5'],
                    stacked: true
                }
            },
            // Churn Reasons Table
            {
                type: 'table',
                title: 'Churn Analysis by Reason',
                position: { x: 100, y: 680 },
                size: { width: 1140, height: 300 },
                data: { 
                    value: '0', 
                    change: '0%',
                    columns: ['Reason', 'Count', 'Percentage', 'Revenue Impact', 'Action'],
                    sortable: true
                }
            },
        ]
    },
    {
        id: '8',
        name: 'Multi-Channel Sales Performance',
        category: 'all',
        description: 'Comprehensive sales channel analysis with performance comparison and growth trends',
        question: 'Como está a evolução de vendas por canal?',
        icon: Activity,
        color: 'blue',
        enterprise: true,
        widgets: [
            // Channel KPIs
            {
                type: 'kpi',
                title: 'Online Sales',
                position: { x: 100, y: 80 },
                size: { width: 240, height: 140 },
                data: { value: '$0', change: '0%', label: 'e-commerce', trend: 'up' }
            },
            {
                type: 'kpi',
                title: 'Retail Sales',
                position: { x: 360, y: 80 },
                size: { width: 240, height: 140 },
                data: { value: '$0', change: '0%', label: 'physical stores', trend: 'neutral' }
            },
            {
                type: 'kpi',
                title: 'Partner Sales',
                position: { x: 620, y: 80 },
                size: { width: 240, height: 140 },
                data: { value: '$0', change: '0%', label: 'resellers', trend: 'up' }
            },
            {
                type: 'kpi',
                title: 'Direct B2B',
                position: { x: 880, y: 80 },
                size: { width: 240, height: 140 },
                data: { value: '$0', change: '0%', label: 'enterprise', trend: 'up' }
            },
            {
                type: 'kpi',
                title: 'Total Sales',
                position: { x: 1140, y: 80 },
                size: { width: 200, height: 140 },
                data: { value: '$0', change: '0%', label: 'all channels' }
            },
            // Channel Comparison
            {
                type: 'chart',
                title: 'Sales by Channel',
                position: { x: 100, y: 240 },
                size: { width: 700, height: 420 },
                data: { 
                    type: 'bar', 
                    series: [0, 0, 0, 0], 
                    labels: ['Online', 'Retail', 'Partner', 'Direct'],
                    showValues: true,
                    colorByValue: true
                }
            },
            // Channel Growth
            {
                type: 'chart',
                title: 'Channel Growth Trends',
                position: { x: 820, y: 240 },
                size: { width: 520, height: 420 },
                data: { 
                    type: 'line', 
                    series: [0, 0, 0, 0, 0, 0],
                    labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
                    multiSeries: true,
                    seriesLabels: ['Online', 'Retail', 'Partner', 'Direct'],
                    showLegend: true,
                    showGrid: true
                }
            },
            // Channel Performance Table
            {
                type: 'table',
                title: 'Channel Performance Matrix',
                position: { x: 100, y: 680 },
                size: { width: 1240, height: 300 },
                data: { 
                    value: '0', 
                    change: '0%',
                    columns: ['Channel', 'Revenue', 'Growth', 'Market Share', 'Efficiency', 'Rank'],
                    sortable: true
                }
            },
        ]
    },
    {
        id: '9',
        name: 'Competitive Benchmark Analysis',
        category: 'strategy',
        description: 'Market position analysis with industry benchmarks and competitive intelligence',
        question: 'Como estamos comparados aos benchmarks de mercado?',
        icon: Globe,
        color: 'purple',
        enterprise: true,
        widgets: [
            // Benchmark KPIs
            {
                type: 'kpi',
                title: 'Market Position',
                position: { x: 100, y: 80 },
                size: { width: 280, height: 140 },
                data: { value: 'N/A', change: '0%', label: 'vs competitors' }
            },
            {
                type: 'kpi',
                title: 'Industry Average',
                position: { x: 400, y: 80 },
                size: { width: 280, height: 140 },
                data: { value: '0%', change: '0%', label: 'growth rate' }
            },
            {
                type: 'kpi',
                title: 'Our Performance',
                position: { x: 700, y: 80 },
                size: { width: 280, height: 140 },
                data: { value: '0%', change: '0%', label: 'growth rate' }
            },
            {
                type: 'kpi',
                title: 'Performance Gap',
                position: { x: 1000, y: 80 },
                size: { width: 240, height: 140 },
                data: { value: '0%', change: '0%', label: 'vs industry' }
            },
            // Benchmark Comparison
            {
                type: 'chart',
                title: 'Performance vs Industry Benchmarks',
                position: { x: 100, y: 240 },
                size: { width: 1140, height: 480 },
                data: { 
                    type: 'bar', 
                    series: [0, 0, 0, 0, 0],
                    labels: ['Revenue Growth', 'Profit Margin', 'Market Share', 'Customer Satisfaction', 'Innovation'],
                    multiSeries: true,
                    seriesLabels: ['Us', 'Industry Avg', 'Top Performer'],
                    showLegend: true,
                    showValues: true
                }
            },
            // Competitive Positioning
            {
                type: 'table',
                title: 'Competitive Positioning Matrix',
                position: { x: 100, y: 740 },
                size: { width: 1140, height: 300 },
                data: { 
                    value: '0', 
                    change: '0%',
                    columns: ['Metric', 'Our Score', 'Industry Avg', 'Top Performer', 'Gap', 'Status'],
                    sortable: true
                }
            },
        ]
    },
    {
        id: '10',
        name: 'Business Health Alert System',
        category: 'all',
        description: 'Real-time monitoring of critical business indicators with alert prioritization',
        question: 'Quais indicadores precisam de atenção imediata?',
        icon: AlertCircle,
        color: 'orange',
        popular: true,
        enterprise: true,
        widgets: [
            // Alert Summary
            {
                type: 'kpi',
                title: 'Critical Alerts',
                position: { x: 100, y: 80 },
                size: { width: 280, height: 160 },
                data: { value: '0', change: '0%', label: 'requires action', trend: 'down', alert: 'critical' }
            },
            {
                type: 'kpi',
                title: 'Warning Indicators',
                position: { x: 400, y: 80 },
                size: { width: 280, height: 160 },
                data: { value: '0', change: '0%', label: 'monitor closely', trend: 'neutral', alert: 'warning' }
            },
            {
                type: 'kpi',
                title: 'All Systems',
                position: { x: 700, y: 80 },
                size: { width: 280, height: 160 },
                data: { value: 'OK', change: '0%', label: 'operational', trend: 'up', alert: 'success' }
            },
            {
                type: 'kpi',
                title: 'Response Time',
                position: { x: 1000, y: 80 },
                size: { width: 240, height: 160 },
                data: { value: '0h', change: '0%', label: 'avg resolution' }
            },
            // Alert Distribution
            {
                type: 'chart',
                title: 'Alert Distribution by Category',
                position: { x: 100, y: 260 },
                size: { width: 600, height: 400 },
                data: { 
                    type: 'bar', 
                    series: [0, 0, 0, 0, 0],
                    labels: ['Revenue', 'Operations', 'Customer', 'Financial', 'Technical'],
                    colorByValue: true
                }
            },
            // Alert Timeline
            {
                type: 'chart',
                title: 'Alert Trend Over Time',
                position: { x: 720, y: 260 },
                size: { width: 520, height: 400 },
                data: { 
                    type: 'line', 
                    series: [0, 0, 0, 0, 0, 0],
                    labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
                    multiSeries: true,
                    seriesLabels: ['Critical', 'Warning', 'Info'],
                    showLegend: true
                }
            },
            // Alert Details Table
            {
                type: 'table',
                title: 'Active Alerts & Actions Required',
                position: { x: 100, y: 680 },
                size: { width: 1140, height: 300 },
                data: { 
                    value: '0', 
                    change: '0%',
                    columns: ['Alert', 'Category', 'Severity', 'Status', 'Assigned', 'ETA'],
                    sortable: true,
                    filterable: true
                }
            },
        ]
    },
    {
        id: '11',
        name: 'AI Business Intelligence Hub',
        category: 'all',
        description: 'Advanced AI-powered analytics with predictive insights and automated recommendations',
        question: 'What are the key AI-driven insights?',
        icon: Sparkles,
        color: 'purple',
        popular: true,
        enterprise: true,
        widgets: [
            // AI Insights Section
            {
                type: 'ai-box',
                title: 'AI Strategic Insights',
                position: { x: 100, y: 80 },
                size: { width: 600, height: 480 },
                data: { 
                    question: 'What are the key trends, predictions, and recommendations?',
                    answer: 'Configure to get AI-powered business insights, predictions, and actionable recommendations...'
                }
            },
            // AI Metrics
            {
                type: 'kpi',
                title: 'AI Confidence Score',
                position: { x: 720, y: 80 },
                size: { width: 260, height: 140 },
                data: { value: '0%', change: '0%', label: 'prediction accuracy' }
            },
            {
                type: 'kpi',
                title: 'Key Opportunities',
                position: { x: 1000, y: 80 },
                size: { width: 260, height: 140 },
                data: { value: '0', change: '0%', label: 'identified' }
            },
            {
                type: 'kpi',
                title: 'Risk Factors',
                position: { x: 720, y: 240 },
                size: { width: 260, height: 140 },
                data: { value: '0', change: '0%', label: 'monitored' }
            },
            {
                type: 'kpi',
                title: 'AI Recommendations',
                position: { x: 1000, y: 240 },
                size: { width: 260, height: 140 },
                data: { value: '0', change: '0%', label: 'actionable' }
            },
            // Predictive Trends
            {
                type: 'chart',
                title: 'AI Predictive Trends',
                position: { x: 720, y: 400 },
                size: { width: 540, height: 360 },
                data: { 
                    type: 'line', 
                    series: [0, 0, 0, 0, 0, 0],
                    labels: ['Now', '+1M', '+2M', '+3M', '+4M', '+5M'],
                    showForecast: true,
                    showConfidence: true,
                    showLegend: true
                }
            },
            // AI Insights Table
            {
                type: 'table',
                title: 'AI-Generated Insights & Recommendations',
                position: { x: 100, y: 580 },
                size: { width: 1160, height: 320 },
                data: { 
                    value: '0', 
                    change: '0%',
                    columns: ['Insight', 'Category', 'Confidence', 'Impact', 'Priority', 'Action'],
                    sortable: true
                }
            },
        ]
    },
]

const CATEGORIES = [
    {
        id: 'for-you',
        label: 'For you',
        items: [
            { id: 'all', label: 'All templates' },
            { id: 'recent', label: 'Recent' },
        ],
    },
    {
        id: 'use-cases',
        label: 'Use cases',
        items: [
            { id: 'meetings', label: 'Meetings & workshops' },
            { id: 'ideation', label: 'Ideation & brainstorming' },
            { id: 'research', label: 'Research & design' },
            { id: 'agile', label: 'Agile workflows' },
            { id: 'strategy', label: 'Strategy & planning' },
            { id: 'diagramming', label: 'Diagramming & mapping' },
            { id: 'presentations', label: 'Presentations & slides' },
        ],
    },
]

const colorClasses = {
    blue: {
        bg: 'from-blue-500/10 via-blue-400/5 to-blue-600/10',
        border: 'border-blue-500/20',
        icon: 'text-blue-500',
        hover: 'hover:border-blue-500/40 hover:from-blue-500/15',
        badge: 'bg-blue-500/20 text-blue-600 dark:text-blue-400 border-blue-500/30',
    },
    green: {
        bg: 'from-green-500/10 via-green-400/5 to-green-600/10',
        border: 'border-green-500/20',
        icon: 'text-green-500',
        hover: 'hover:border-green-500/40 hover:from-green-500/15',
        badge: 'bg-green-500/20 text-green-600 dark:text-green-400 border-green-500/30',
    },
    purple: {
        bg: 'from-purple-500/10 via-purple-400/5 to-purple-600/10',
        border: 'border-purple-500/20',
        icon: 'text-purple-500',
        hover: 'hover:border-purple-500/40 hover:from-purple-500/15',
        badge: 'bg-purple-500/20 text-purple-600 dark:text-purple-400 border-purple-500/30',
    },
    orange: {
        bg: 'from-orange-500/10 via-orange-400/5 to-orange-600/10',
        border: 'border-orange-500/20',
        icon: 'text-orange-500',
        hover: 'hover:border-orange-500/40 hover:from-orange-500/15',
        badge: 'bg-orange-500/20 text-orange-600 dark:text-orange-400 border-orange-500/30',
    },
    indigo: {
        bg: 'from-indigo-500/10 via-indigo-400/5 to-indigo-600/10',
        border: 'border-indigo-500/20',
        icon: 'text-indigo-500',
        hover: 'hover:border-indigo-500/40 hover:from-indigo-500/15',
        badge: 'bg-indigo-500/20 text-indigo-600 dark:text-indigo-400 border-indigo-500/30',
    },
    teal: {
        bg: 'from-teal-500/10 via-teal-400/5 to-teal-600/10',
        border: 'border-teal-500/20',
        icon: 'text-teal-500',
        hover: 'hover:border-teal-500/40 hover:from-teal-500/15',
        badge: 'bg-teal-500/20 text-teal-600 dark:text-teal-400 border-teal-500/30',
    },
    red: {
        bg: 'from-red-500/10 via-red-400/5 to-red-600/10',
        border: 'border-red-500/20',
        icon: 'text-red-500',
        hover: 'hover:border-red-500/40 hover:from-red-500/15',
        badge: 'bg-red-500/20 text-red-600 dark:text-red-400 border-red-500/30',
    },
}

// Ícone de Templates - Design Minimalista e Geométrico
const TemplatesIcon = ({ className, color = "currentColor" }: { className?: string; color?: string }) => (
    <svg
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={className}
    >
        {/* Grid base */}
        <rect x="2" y="2" width="8" height="8" rx="1" stroke={color} strokeWidth="1.5" fill="none" opacity="0.6"/>
        <rect x="12" y="2" width="8" height="8" rx="1" stroke={color} strokeWidth="1.5" fill="none" opacity="0.6"/>
        <rect x="2" y="12" width="8" height="8" rx="1" stroke={color} strokeWidth="1.5" fill="none" opacity="0.6"/>
        <rect x="12" y="12" width="8" height="8" rx="1" stroke={color} strokeWidth="1.5" fill="none" opacity="0.6"/>
        
        {/* Elementos de dashboard dentro dos grids */}
        <line x1="4" y1="5" x2="8" y2="5" stroke={color} strokeWidth="1" opacity="0.8"/>
        <line x1="4" y1="7" x2="7" y2="7" stroke={color} strokeWidth="1" opacity="0.8"/>
        <circle cx="6" cy="9" r="1" fill={color} opacity="0.8"/>
        
        <line x1="14" y1="5" x2="18" y2="5" stroke={color} strokeWidth="1" opacity="0.8"/>
        <rect x="14" y="7" width="3" height="2" rx="0.5" fill={color} opacity="0.8"/>
        
        <path d="M4 14 L8 18" stroke={color} strokeWidth="1.5" opacity="0.8"/>
        <path d="M4 18 L8 14" stroke={color} strokeWidth="1.5" opacity="0.8"/>
        
        <rect x="14" y="14" width="4" height="4" rx="0.5" fill={color} opacity="0.4"/>
    </svg>
)

// Helper to convert API template to UI template format
const convertApiTemplateToUITemplate = (apiTemplate: ApiTemplate): Template => {
    // Map icon string to React component if needed
    let iconComponent: React.ElementType | undefined = undefined
    if ('icon' in apiTemplate && apiTemplate.icon) {
        // If icon is already a component (from hardcoded), use it
        // Otherwise, try to map icon string to component
        const iconMap: Record<string, React.ElementType> = {
            'calendar': Calendar,
            'chart': BarChart3,
            'trending': TrendingUp,
            'target': Target,
            'layout': Layout,
            'sparkles': Sparkles,
            'dollar': DollarSign,
            'users': Users,
            'map': MapPin,
            'pie': PieChart,
            'activity': Activity,
            'briefcase': Briefcase,
            'globe': Globe,
            'zap': Zap,
            'line': LineChart,
            'award': Award,
            'alert': AlertCircle,
        }
        if (typeof apiTemplate.icon === 'function') {
            iconComponent = apiTemplate.icon as React.ElementType
        } else if (typeof apiTemplate.icon === 'string') {
            iconComponent = iconMap[apiTemplate.icon.toLowerCase()] || Layout
        }
    }
    
    return {
        ...apiTemplate,
        icon: iconComponent,
    }
}

export function TemplatesDialog() {
    const {
        isOpen,
        close,
        selectedCategory,
        setSelectedCategory,
        searchQuery,
        setSearchQuery,
        showWhenCreatingBoard,
        setShowWhenCreatingBoard,
        templates,
        categories,
        isLoading,
        fetchTemplates,
        fetchCategories,
        applyTemplate,
    } = useTemplatesStore()
    const { addWidget } = useWidgetStore()
    const { getViewportCenter } = useCanvasStore()
    const { resolvedTheme } = useTheme()
    const isDark = resolvedTheme === 'dark'
    const { currentDashboard } = useDashboardStore()

    // Fetch templates and categories when dialog opens
    useEffect(() => {
        if (isOpen) {
            console.log('[TemplatesDialog] Fetching templates from backend...')
            fetchTemplates({
                category: selectedCategory !== 'all' ? selectedCategory : undefined,
                search: searchQuery || undefined,
            }).then((result) => {
                // result is Template[] or void, check if it's an array
                if (Array.isArray(result)) {
                    console.log('[TemplatesDialog] Templates fetched from backend:', result.length)
                }
            }).catch((error) => {
                // Error already handled in store, just log for debugging
                console.warn('[TemplatesDialog] API call failed, fallback templates will be used')
            })
            fetchCategories().catch((error: any) => {
                // Categories are optional - error already handled in store with fallback
                // 422 errors are expected for optional endpoints - don't log
                const is422 = error?.response?.status === 422;
                if (process.env.NODE_ENV === 'development' && !is422) {
                    // Only log non-422 errors
                    console.log('[TemplatesDialog] ℹ️ Categories API failed (using hardcoded categories)')
                }
            })
        }
    }, [isOpen, fetchTemplates, fetchCategories])
    
    // Refetch when category or search changes (only if we have templates from backend)
    useEffect(() => {
        if (isOpen && templates.length > 0) {
            fetchTemplates({
                category: selectedCategory !== 'all' ? selectedCategory : undefined,
                search: searchQuery || undefined,
            }).catch((error) => {
                console.warn('[TemplatesDialog] Failed to refetch templates:', error)
            })
        }
    }, [selectedCategory, searchQuery, isOpen, templates.length, fetchTemplates])

    const filteredTemplates = useMemo(() => {
        // Convert API templates to UI format and use fallback if backend is empty
        const convertedTemplates = templates.length > 0 ? templates.map(convertApiTemplateToUITemplate) : []
        const allTemplates = convertedTemplates.length > 0 ? convertedTemplates : TEMPLATES
        
        // Only log in development to avoid console spam
        if (process.env.NODE_ENV === 'development') {
            console.log('[TemplatesDialog] 📋 Templates:', {
                fromBackend: templates.length,
                converted: convertedTemplates.length,
                fromFallback: TEMPLATES.length,
                total: allTemplates.length,
                usingFallback: convertedTemplates.length === 0
            })
        }
        
        let filtered = allTemplates

        if (selectedCategory !== 'all') {
            filtered = filtered.filter((t) => t.category === selectedCategory || t.category === 'all')
        }

        if (searchQuery) {
            const query = searchQuery.toLowerCase()
            filtered = filtered.filter(
                (t) =>
                    t.name.toLowerCase().includes(query) ||
                    t.description?.toLowerCase().includes(query) ||
                    t.question?.toLowerCase().includes(query)
            )
        }

        return filtered
    }, [templates, selectedCategory, searchQuery])

    const handleSelectTemplate = async (template: Template) => {
        if (!currentDashboard) {
            console.error('No dashboard selected')
            return
        }

        const viewportCenter = getViewportCenter()
        
        try {
            // Use applyTemplate API endpoint if available, otherwise fallback to manual widget creation
            if (template.id && template.id !== '1' && template.id !== '2' && template.id !== '3') {
                // Real template from backend - use applyTemplate API
                const result = await applyTemplate(template.id, currentDashboard.id)
                // Widgets are created by the backend, just close the dialog
                close()
            } else if (template.widgets) {
                // Fallback for hardcoded templates (temporary)
                await Promise.all(template.widgets.map((widget) => 
                    addWidget({
                        ...widget,
                        position: {
                            x: widget.position.x + (viewportCenter.x - 600),
                            y: widget.position.y + (viewportCenter.y - 400),
                        }
                    })
                ))
                close()
            } else {
                // No widgets to create
                close()
            }
        } catch (error) {
            console.error('Error applying template:', error)
            // Could add toast notification here for better UX
            alert(`Failed to apply template: ${error instanceof Error ? error.message : 'Unknown error'}`)
        }
    }

    if (!isOpen) return null

    const modalStyle = {
        borderRadius: "1rem",
        border: isDark 
            ? "1px solid rgba(255, 255, 255, 0.08)" 
            : "1px solid rgba(0, 0, 0, 0.08)",
        background: isDark 
            ? "rgba(15, 23, 42, 0.98)" 
            : "rgba(255, 255, 255, 0.98)",
        backdropFilter: "blur(40px) saturate(180%)",
        WebkitBackdropFilter: "blur(40px) saturate(180%)",
        boxShadow: isDark 
            ? "0 20px 60px rgba(0, 0, 0, 0.5), 0 4px 16px rgba(0, 0, 0, 0.3)" 
            : "0 20px 60px rgba(0, 0, 0, 0.15), 0 4px 16px rgba(0, 0, 0, 0.1)",
    }

    return (
        <AnimatePresence>
            <div className="fixed inset-0 z-[100] pointer-events-auto">
                {/* Backdrop */}
                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.15 }}
                    className="fixed inset-0 bg-black/5 backdrop-blur-[1px]"
                    onClick={close}
                />

                {/* Modal */}
                <motion.div
                    initial={{ opacity: 0, scale: 0.96, y: 20 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.96, y: 20 }}
                    transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
                    className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[1200px] h-[750px] flex overflow-hidden rounded-2xl"
                    style={modalStyle}
                    onClick={(e) => e.stopPropagation()}
                >
                    {/* Left Sidebar */}
                    <div className={cn(
                        "w-52 flex flex-col flex-shrink-0",
                        isDark ? "bg-gray-900/30 border-r border-white/5" : "bg-gray-50/60 border-r border-black/5"
                    )}>
                        <div className="p-5 border-b" style={{ borderColor: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)' }}>
                            <div className="flex items-center gap-2.5">
                                <div className={cn(
                                    "w-9 h-9 rounded-lg flex items-center justify-center",
                                    "bg-blue-500/10 border border-blue-500/20"
                                )}>
                                    <TemplatesIcon className="w-5 h-5 text-blue-500" color="currentColor" />
                                </div>
                                <div>
                                    <h2 className="text-base font-semibold text-foreground leading-tight">Templates</h2>
                                    <p className="text-[10px] text-muted-foreground leading-tight mt-0.5">Enterprise</p>
                                </div>
                            </div>
                        </div>

                        <div className="flex-1 overflow-y-auto p-4 space-y-5">
                            {CATEGORIES.map((category) => (
                                <div key={category.id}>
                                    <h3 className={cn(
                                        "text-[9px] font-semibold uppercase tracking-wider mb-2.5 px-2.5",
                                        isDark ? "text-white/25" : "text-gray-400"
                                    )}>
                                        {category.label}
                                    </h3>
                                    <div className="space-y-0.5">
                                        {category.items.map((item) => (
                                            <button
                                                key={item.id}
                                                onClick={() => setSelectedCategory(item.id)}
                                                className={cn(
                                                    "w-full text-left px-2.5 py-2 rounded-md text-xs transition-all duration-200",
                                                    "flex items-center gap-2 group",
                                                    selectedCategory === item.id
                                                        ? "bg-blue-500/12 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400 font-medium"
                                                        : "text-foreground/60 hover:text-foreground hover:bg-gray-100/50 dark:hover:bg-white/5",
                                                )}
                                            >
                                                <span className="text-xs leading-tight">{item.label}</span>
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Main Content */}
                    <div className="flex-1 flex flex-col overflow-hidden">
                        {/* Top Bar */}
                        <div className={cn(
                            "px-5 py-4 border-b flex items-center gap-3",
                            isDark ? "border-white/5" : "border-black/5"
                        )}>
                            {/* Search */}
                            <div className="flex-1 relative">
                                <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground/50" />
                                <Input
                                    type="text"
                                    placeholder="Search templates..."
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                    className={cn(
                                        "pl-9 h-9 text-xs",
                                        isDark 
                                            ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                            : "bg-white/60 border-black/8 focus:border-black/15 focus:bg-white"
                                    )}
                                />
                            </div>

                            {/* Checkbox */}
                            <div className="flex items-center gap-2.5">
                                <Checkbox
                                    id="show-when-creating"
                                    checked={showWhenCreatingBoard}
                                    onCheckedChange={(checked) => setShowWhenCreatingBoard(checked as boolean)}
                                />
                                <label
                                    htmlFor="show-when-creating"
                                    className="text-[11px] text-foreground/60 cursor-pointer select-none"
                                >
                                    Show when creating
                                </label>
                            </div>

                            {/* Close Button */}
                            <Button
                                variant="ghost"
                                size="icon"
                                onClick={close}
                                className="h-8 w-8"
                            >
                                <X className="w-3.5 h-3.5" />
                            </Button>
                        </div>

                        {/* Header */}
                        <div className={cn(
                            "px-5 py-4 flex items-center justify-between",
                            isDark ? "border-b border-white/5" : "border-b border-black/5"
                        )}>
                            <div>
                                <h1 className="text-xl font-semibold text-foreground mb-0.5">
                                    {selectedCategory === 'all' 
                                        ? 'All templates' 
                                        : categories.find(c => c === selectedCategory) 
                                            ? selectedCategory.charAt(0).toUpperCase() + selectedCategory.slice(1)
                                            : CATEGORIES.flatMap(c => c.items).find(i => i.id === selectedCategory)?.label || 'All templates'}
                                </h1>
                                <p className="text-[11px] text-muted-foreground">
                                    {filteredTemplates.length} {filteredTemplates.length === 1 ? 'template' : 'templates'}
                                </p>
                            </div>
                            <Select defaultValue="recommended">
                                <SelectTrigger className="w-[140px] h-9 text-xs">
                                    <SelectValue placeholder="Sort by" />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="recommended">Recommended</SelectItem>
                                    <SelectItem value="popular">Most Popular</SelectItem>
                                    <SelectItem value="recent">Most Recent</SelectItem>
                                    <SelectItem value="name">Name (A-Z)</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>

                        {/* Templates Grid */}
                        <div className="flex-1 overflow-y-auto p-4">
                            {isLoading ? (
                                <div className="flex items-center justify-center h-96">
                                    <div className="text-center">
                                        <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-2"></div>
                                        <p className="text-sm text-muted-foreground">Loading templates...</p>
                                    </div>
                                </div>
                            ) : (
                                <div className="grid grid-cols-3 gap-2.5">
                                    {filteredTemplates.map((template) => {
                                        // Handle icon - can be string (from API) or React component (from hardcoded)
                                        const Icon = typeof template.icon === 'function' 
                                            ? template.icon 
                                            : (template.icon ? Layout : Sparkles) // Default icon if string
                                        // Convert hex color to color name for colorClasses
                                        const colorName = template.color?.startsWith('#') 
                                            ? (template.color === '#3B82F6' ? 'blue' : 
                                               template.color === '#10B981' ? 'green' :
                                               template.color === '#8B5CF6' ? 'purple' :
                                               template.color === '#F59E0B' ? 'orange' : 'blue')
                                            : (template.color || 'blue')
                                        const colors = colorClasses[colorName as keyof typeof colorClasses] || colorClasses.blue
                                    
                                    return (
                                        <motion.button
                                            key={template.id}
                                            onClick={() => handleSelectTemplate(template)}
                                            whileHover={{ y: -2 }}
                                            whileTap={{ scale: 0.98 }}
                                            className={cn(
                                                "text-left group relative",
                                                "transition-all duration-200"
                                            )}
                                        >
                                            {/* Card Container */}
                                            <div className={cn(
                                                "relative rounded-lg overflow-hidden",
                                                "border transition-all duration-200",
                                                isDark 
                                                    ? "border-white/8 bg-gray-900/20" 
                                                    : "border-gray-200/60 bg-white/80",
                                                colors.hover,
                                                "shadow-sm group-hover:shadow-md group-hover:border-blue-300/30 dark:group-hover:border-blue-700/30"
                                            )}>
                                                {/* Badges */}
                                                {(template.popular || template.enterprise) && (
                                                    <div className="absolute top-2 right-2 z-10 flex gap-1">
                                                        {template.popular && (
                                                            <div className={cn(
                                                                "px-1.5 py-0.5 rounded text-[8px] font-semibold uppercase tracking-wider",
                                                                "bg-blue-500/15 text-blue-600 dark:text-blue-400",
                                                                "border border-blue-500/20"
                                                            )}>
                                                                Popular
                                                            </div>
                                                        )}
                                                        {template.enterprise && (
                                                            <div className={cn(
                                                                "px-1.5 py-0.5 rounded text-[8px] font-semibold uppercase tracking-wider",
                                                                "bg-gray-800/40 dark:bg-white/8 text-gray-700 dark:text-white/70",
                                                                "border border-gray-300/20 dark:border-white/15"
                                                            )}>
                                                                Enterprise
                                                            </div>
                                                        )}
                                                    </div>
                                                )}

                                                {/* Thumbnail Preview */}
                                                <div className={cn(
                                                    "w-full aspect-[4/3] relative overflow-hidden",
                                                    "bg-gradient-to-br",
                                                    colors.bg,
                                                    "flex items-center justify-center p-3"
                                                )}>
                                                    {/* Icon Container */}
                                                    <div className={cn(
                                                        "w-12 h-12 rounded-lg flex items-center justify-center",
                                                        "bg-white/30 dark:bg-white/8",
                                                        "backdrop-blur-sm border border-white/40 dark:border-white/20",
                                                        colors.icon,
                                                        "shadow-sm"
                                                    )}>
                                                        <Icon className="w-6 h-6" />
                                                    </div>
                                                </div>

                                                {/* Content */}
                                                <div className="p-3 space-y-1.5 bg-white/60 dark:bg-gray-900/40 backdrop-blur-sm">
                                                    <div>
                                                        <h3 className="text-xs font-semibold text-foreground group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors line-clamp-1 leading-tight">
                                                            {template.name}
                                                        </h3>
                                                        <p className={cn(
                                                            "text-[9px] mt-0.5",
                                                            isDark ? "text-white/45" : "text-gray-500"
                                                        )}>
                                                            {template.category || 'Template'}
                                                        </p>
                                                    </div>
                                                    
                                                    <p className={cn(
                                                        "text-[10px] leading-snug line-clamp-2",
                                                        isDark ? "text-white/65" : "text-gray-600"
                                                    )}>
                                                        {template.description}
                                                    </p>

                                                    {/* Question Badge - More Subtle */}
                                                    {template.question && (
                                                        <div className={cn(
                                                            "pt-1.5 mt-1.5 border-t",
                                                            isDark ? "border-white/8" : "border-gray-200/60"
                                                        )}>
                                                            <p className={cn(
                                                                "text-[8px] font-medium uppercase tracking-wide mb-0.5",
                                                                isDark ? "text-white/35" : "text-gray-400"
                                                            )}>
                                                                Question
                                                            </p>
                                                            <p className={cn(
                                                                "text-[9px] italic line-clamp-1 leading-tight",
                                                                isDark ? "text-white/55" : "text-gray-500"
                                                            )}>
                                                                "{template.question}"
                                                            </p>
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                        </motion.button>
                                    )
                                })}
                                    {filteredTemplates.length === 0 && !isLoading && (
                                        <div className="col-span-3 flex flex-col items-center justify-center h-96 text-center">
                                            <div className="w-16 h-16 rounded-xl bg-gray-100/50 dark:bg-gray-800/50 flex items-center justify-center mb-4">
                                                <Search className="w-6 h-6 text-muted-foreground/60" />
                                            </div>
                                            <p className="text-base font-medium text-foreground mb-1.5">
                                                No templates found
                                            </p>
                                            <p className="text-xs text-muted-foreground">
                                                Try adjusting your search or category filter
                                            </p>
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                </motion.div>
            </div>
        </AnimatePresence>
    )
}
