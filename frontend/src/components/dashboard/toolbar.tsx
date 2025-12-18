"use client"

import { useState, useEffect, useRef } from "react"
import { 
    Type, 
    Layout, 
    BarChart3, 
    Table as TableIcon,
    Lock,
    Unlock,
    MousePointer2,
    Hash as HashIcon,
    Loader2,
} from "lucide-react"
import { useWidgetStore } from "@/store/widget-store"
import { useCanvasStore } from "@/store/canvas-store"
import { useTemplatesStore } from "@/store/templates-store"
import { useCanvasLockStore } from "@/store/canvas-lock-store"
import { useToolbarStore } from "@/store/toolbar-store"
import { useDashboardStore } from "@/store/dashboard-store"
import { useTheme } from "next-themes"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { ToolbarChartsMenu } from "./toolbar-charts-menu"
import { ToolbarUploadButton } from "./toolbar-upload-button"
import { filesApi } from "@/lib/api/files"

export function Toolbar() {
    const { addWidget } = useWidgetStore()
    const { getViewportCenter, snapPosition } = useCanvasStore()
    const { open: openTemplates } = useTemplatesStore()
    const { isLocked, toggleLock } = useCanvasLockStore()
    const { activeTool, setActiveTool } = useToolbarStore()
    const { currentDashboard } = useDashboardStore()
    const { theme, resolvedTheme } = useTheme()
    const [mounted, setMounted] = useState(false)
    const [chartsMenuOpen, setChartsMenuOpen] = useState(false)
    const [isUploading, setIsUploading] = useState(false)
    const chartsButtonRef = useRef<HTMLButtonElement>(null)

    useEffect(() => {
        setMounted(true)
    }, [])

    const currentTheme = resolvedTheme || theme || 'light'
    const isDark = currentTheme === 'dark'

    const handleSelectMouse = () => {
        const newTool = activeTool === 'mouse' ? null : 'mouse'
        setActiveTool(newTool)
    }

    const handleSelectText = () => {
        setActiveTool(activeTool === 'text' ? null : 'text')
    }

    const handleSelectKPI = () => {
        setActiveTool(activeTool === 'kpi' ? null : 'kpi')
    }

    const handleAddChart = (chartType: 'bar' | 'pie' | 'line' | 'scatter') => {
        setActiveTool(activeTool === `chart-${chartType}` ? null : `chart-${chartType}`)
    }

    const handleSelectTable = () => {
        setActiveTool(activeTool === 'table' ? null : 'table')
    }


    const handleUpload = async (files: FileList) => {
        if (!currentDashboard) {
            alert("Please select a dashboard first")
            return
        }

        setIsUploading(true)
        const fileArray = Array.from(files)
        
        try {
            for (const file of fileArray) {
                const fileType = file.type.toLowerCase()
                const fileName = file.name.toLowerCase()
                
                // Determine file type and upload accordingly
                if (fileName.endsWith('.csv')) {
                    // Upload CSV and create table widget
                    try {
                        const response = await filesApi.uploadCSV(file, (progress) => {
                            // Could show progress toast here
                        })
                        
                        // Create table widget with CSV data
                        const center = getViewportCenter()
                        await addWidget({
                            type: 'table',
                            title: file.name.replace('.csv', ''),
                            position: snapPosition(center.x, center.y),
                            size: { width: 600, height: 400 },
                            data: {
                                source: 'upload',
                                file_id: response.file_id,
                                columns: response.columns,
                                preview: response.preview,
                                data: response.data,
                            },
                        }, currentDashboard.id)
                        
                        console.log(`CSV "${file.name}" uploaded successfully`)
                    } catch (error) {
                        console.error('Error uploading CSV:', error)
                        alert(`Failed to upload CSV "${file.name}": ${error instanceof Error ? error.message : 'Unknown error'}`)
                    }
                } else if (fileName.endsWith('.xlsx') || fileName.endsWith('.xls')) {
                    // Upload Excel and create table widget
                    try {
                        const response = await filesApi.uploadExcel(file, (progress) => {
                            // Could show progress toast here
                        })
                        
                        // Create table widget with Excel data (use first sheet)
                        const firstSheet = response.sheets[0]
                        const center = getViewportCenter()
                        await addWidget({
                            type: 'table',
                            title: file.name.replace(/\.(xlsx|xls)$/i, ''),
                            position: snapPosition(center.x, center.y),
                            size: { width: 600, height: 400 },
                            data: {
                                source: 'upload',
                                file_id: response.file_id,
                                columns: response.columns[firstSheet] || [],
                                preview: response.preview[firstSheet] || [],
                                data: response.data[firstSheet] || [],
                                sheets: response.sheets,
                            },
                        }, currentDashboard.id)
                        
                        console.log(`Excel "${file.name}" uploaded successfully`)
                    } catch (error) {
                        console.error('Error uploading Excel:', error)
                        alert(`Failed to upload Excel "${file.name}": ${error instanceof Error ? error.message : 'Unknown error'}`)
                    }
                } else if (fileType.startsWith('image/')) {
                    // Upload image and create image widget
                    try {
                        const response = await filesApi.uploadImage(file, undefined, (progress) => {
                            // Could show progress toast here
                        })
                        
                        // Create image widget
                        const center = getViewportCenter()
                        await addWidget({
                            type: 'text', // Using text widget for images for now
                            title: file.name,
                            position: snapPosition(center.x, center.y),
                            size: { width: 400, height: 300 },
                            data: {
                                source: 'upload',
                                file_id: response.file_id,
                                url: response.url,
                                type: 'image',
                                filename: response.filename,
                            },
                        }, currentDashboard.id)
                        
                        console.log(`Image "${file.name}" uploaded successfully`)
                    } catch (error) {
                        console.error('Error uploading image:', error)
                        alert(`Failed to upload image "${file.name}": ${error instanceof Error ? error.message : 'Unknown error'}`)
                    }
                } else if (fileName.endsWith('.pdf')) {
                    // Upload PDF
                    try {
                        const response = await filesApi.uploadPDF(file, undefined, (progress) => {
                            // Could show progress toast here
                        })
                        
                        // Create text widget with PDF link/info
                        const center = getViewportCenter()
                        await addWidget({
                            type: 'text',
                            title: file.name.replace('.pdf', ''),
                            position: snapPosition(center.x, center.y),
                            size: { width: 500, height: 300 },
                            data: {
                                source: 'upload',
                                file_id: response.file_id,
                                url: response.url,
                                type: 'pdf',
                                filename: response.filename,
                            },
                        }, currentDashboard.id)
                        
                        console.log(`PDF "${file.name}" uploaded successfully`)
                    } catch (error) {
                        console.error('Error uploading PDF:', error)
                        alert(`Failed to upload PDF "${file.name}": ${error instanceof Error ? error.message : 'Unknown error'}`)
                    }
                } else {
                    // Generic file upload
                    try {
                        const response = await filesApi.uploadFile(file, undefined, (progress) => {
                            // Could show progress toast here
                        })
                        
                        // Create text widget with file info
                        const center = getViewportCenter()
                        await addWidget({
                            type: 'text',
                            title: file.name,
                            position: snapPosition(center.x, center.y),
                            size: { width: 400, height: 200 },
                            data: {
                                source: 'upload',
                                file_id: response.file_id,
                                url: response.url,
                                type: response.type,
                                filename: response.filename,
                            },
                        }, currentDashboard.id)
                        
                        console.log(`File "${file.name}" uploaded successfully`)
                    } catch (error) {
                        console.error('Error uploading file:', error)
                        alert(`Failed to upload "${file.name}": ${error instanceof Error ? error.message : 'Unknown error'}`)
                    }
                }
            }
        } finally {
            setIsUploading(false)
        }
    }

    if (!mounted) return null

    const toolbarStyle = {
        borderRadius: "0.75rem",
        padding: "0.5rem",
        border: isDark 
            ? "1px solid rgba(255, 255, 255, 0.08)" 
            : "1px solid rgba(0, 0, 0, 0.08)",
        background: isDark 
            ? "rgba(15, 23, 42, 0.4)" 
            : "rgba(255, 255, 255, 0.6)",
        backdropFilter: "blur(32px) saturate(180%)",
        WebkitBackdropFilter: "blur(32px) saturate(180%)",
        boxShadow: isDark 
            ? "0 4px 20px rgba(0, 0, 0, 0.25), 0 1px 4px rgba(0, 0, 0, 0.15)" 
            : "0 4px 20px rgba(0, 0, 0, 0.08), 0 1px 4px rgba(0, 0, 0, 0.04)",
    }

    const buttonBaseClass = cn(
        "h-9 w-9 rounded-lg transition-all duration-200",
        "flex items-center justify-center",
        "hover:bg-accent active:scale-95",
        isDark
            ? "text-white/90 hover:bg-white/8 active:bg-white/12"
            : "text-gray-900 hover:bg-black/5 active:bg-black/10"
    )

    return (
        <div 
            className="fixed top-1/2 -translate-y-1/2 left-4 z-40 flex flex-col gap-1 transition-all duration-200 pointer-events-none"
            style={toolbarStyle}
        >
            <TooltipProvider delayDuration={0}>
                <div className="flex flex-col gap-1 pointer-events-auto relative" data-tour="toolbar">
                    {/* Mouse - Selection Mode */}
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <button
                                data-tour="mouse-tool"
                                onClick={handleSelectMouse}
                                className={cn(
                                    buttonBaseClass,
                                    activeTool === 'mouse' && "bg-primary/20"
                                )}
                                aria-label="Selection Mode"
                            >
                                <MousePointer2 className="w-4.5 h-4.5" />
                            </button>
                        </TooltipTrigger>
                        <TooltipContent side="right" className="text-xs">
                            <div className="font-medium">Selection Mode</div>
                        </TooltipContent>
                    </Tooltip>

                    {/* Templates */}
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <button
                                data-tour="templates-tool"
                                onClick={openTemplates}
                                className={buttonBaseClass}
                                aria-label="Templates"
                            >
                                <Layout className="w-4.5 h-4.5" />
                            </button>
                        </TooltipTrigger>
                        <TooltipContent side="right" className="text-xs">
                            <div className="font-medium">Templates</div>
                        </TooltipContent>
                    </Tooltip>

                    {/* Separator */}
                    <div className={cn(
                        "h-px my-1.5",
                        isDark ? "bg-white/10" : "bg-black/10"
                    )} />

                    {/* Text */}
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <button
                                data-tour="text-tool"
                                onClick={handleSelectText}
                                className={cn(
                                    buttonBaseClass,
                                    activeTool === 'text' && "bg-primary/20"
                                )}
                                aria-label="Add Text"
                            >
                                <Type className="w-4.5 h-4.5" />
                            </button>
                        </TooltipTrigger>
                        <TooltipContent side="right" className="text-xs">
                            <div className="font-medium">Text</div>
                        </TooltipContent>
                    </Tooltip>

                    {/* KPI */}
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <button
                                data-tour="kpi-tool"
                                onClick={handleSelectKPI}
                                className={cn(
                                    buttonBaseClass,
                                    activeTool === 'kpi' && "bg-primary/20"
                                )}
                                aria-label="Add KPI"
                            >
                                <span className="text-sm font-bold leading-none">123</span>
                            </button>
                        </TooltipTrigger>
                        <TooltipContent side="right" className="text-xs">
                            <div className="font-medium">KPI</div>
                        </TooltipContent>
                    </Tooltip>

                    {/* Charts - with submenu */}
                    <div className="relative">
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <button
                                    data-tour="charts-tool"
                                    ref={chartsButtonRef}
                                    onClick={() => {
                                        if (chartsMenuOpen) {
                                            setChartsMenuOpen(false)
                                        } else {
                                            setChartsMenuOpen(true)
                                        }
                                    }}
                                    className={cn(
                                        buttonBaseClass,
                                        chartsMenuOpen && "bg-accent",
                                        activeTool?.startsWith('chart-') && "bg-primary/20"
                                    )}
                                    aria-label="Charts"
                                >
                                    <BarChart3 className="w-4.5 h-4.5" />
                                </button>
                            </TooltipTrigger>
                            <TooltipContent side="right" className="text-xs">
                                <div className="font-medium">Charts</div>
                            </TooltipContent>
                        </Tooltip>
                        <ToolbarChartsMenu
                            isOpen={chartsMenuOpen}
                            onClose={() => setChartsMenuOpen(false)}
                            onSelect={handleAddChart}
                            triggerRef={chartsButtonRef}
                        />
                    </div>

                    {/* Table */}
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <button
                                data-tour="table-tool"
                                onClick={handleSelectTable}
                                className={cn(
                                    buttonBaseClass,
                                    activeTool === 'table' && "bg-primary/20"
                                )}
                                aria-label="Table"
                            >
                                <TableIcon className="w-4.5 h-4.5" />
                            </button>
                        </TooltipTrigger>
                        <TooltipContent side="right" className="text-xs">
                            <div className="font-medium">Table</div>
                        </TooltipContent>
                    </Tooltip>

                    {/* Upload */}
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <div data-tour="upload-tool" className="relative">
                                <ToolbarUploadButton 
                                    onUpload={handleUpload} 
                                    disabled={isUploading || !currentDashboard}
                                />
                                {isUploading && (
                                    <div className="absolute inset-0 flex items-center justify-center bg-background/50 rounded-lg">
                                        <Loader2 className="w-4 h-4 animate-spin text-primary" />
                                    </div>
                                )}
                            </div>
                        </TooltipTrigger>
                        <TooltipContent side="right" className="text-xs">
                            <div className="font-medium">Upload</div>
                            {!currentDashboard && (
                                <div className="text-muted-foreground text-[10px] mt-1">
                                    Select a dashboard first
                                </div>
                            )}
                        </TooltipContent>
                    </Tooltip>

                    {/* Separator */}
                    <div className={cn(
                        "h-px my-1.5",
                        isDark ? "bg-white/10" : "bg-black/10"
                    )} />

                    {/* Lock/Unlock Canvas */}
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <button
                                onClick={toggleLock}
                                className={cn(
                                    buttonBaseClass,
                                    isLocked && "bg-primary/20"
                                )}
                                aria-label={isLocked ? "Unlock canvas" : "Lock canvas"}
                            >
                                {isLocked ? (
                                    <Lock className="w-4.5 h-4.5" />
                                ) : (
                                    <Unlock className="w-4.5 h-4.5" />
                                )}
                            </button>
                        </TooltipTrigger>
                        <TooltipContent side="right" className="text-xs">
                            <div className="font-medium">
                                {isLocked ? "Unlock Canvas" : "Lock Canvas"}
                            </div>
                            <div className="text-muted-foreground text-[10px]">
                                {isLocked ? "Enable widget movement" : "Prevent widget movement"}
                            </div>
                        </TooltipContent>
                    </Tooltip>
                </div>
            </TooltipProvider>
        </div>
    )
}
