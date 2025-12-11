"use client"

import { useRef, useEffect, useState } from "react"
import { useCanvasStore } from "@/store/canvas-store"
import { useSidebarStore } from "@/store/sidebar-store"
import { useWidgetStore, Widget } from "@/store/widget-store"
import { useToolbarStore } from "@/store/toolbar-store"
import { useDashboardStore } from "@/store/dashboard-store"
import { usePlanetStore } from "@/store/planet-store"
import { Toolbar } from "@/components/dashboard/toolbar"
import { CanvasControls } from "@/components/dashboard/canvas-controls"
import { AISearchBar } from "@/components/dashboard/ai-search-bar"
import { TextToolbarFloating } from "@/components/dashboard/text-toolbar-floating"
import { SelectionBox } from "@/components/dashboard/selection-box"
import { ConnectionLine } from "@/components/dashboard/connection-line"
import { usePipelineStore } from "@/store/pipeline-store"
import { useAIHistoryStore } from "@/store/ai-history-store"
import { cn } from "@/lib/utils"
import { useTheme } from "next-themes"

export function Canvas({ children }: { children: React.ReactNode }) {
    const containerRef = useRef<HTMLDivElement>(null)
    const dragStartRef = useRef<{ x: number; y: number; startPosition: { x: number; y: number } } | null>(null)
    const [selectionBox, setSelectionBox] = useState<{ start: { x: number; y: number }; end: { x: number; y: number } } | null>(null)
    const { scale, position, setPosition, zoomIn, zoomOut, resetView, isDragging, setIsDragging, snapPosition, getViewportCenter, findVisiblePositionInViewport, findNextGridPosition, snapToGrid, gridSize } = useCanvasStore()
    const { isOpen: isSidebarOpen } = useSidebarStore()
    const { selectWidget, addWidget, widgets, selectWidgets, removeWidgets, selectedWidgetIds, connections, pendingWidgets } = useWidgetStore()
    const { activeTool, setActiveTool } = useToolbarStore()
    const { openForWidget } = usePipelineStore()
    const { setIsOpen: setAIHistoryOpen } = useAIHistoryStore()
    const { currentDashboard, updateDashboard, createDashboard } = useDashboardStore()
    const { currentPlanet } = usePlanetStore()
    const { theme, resolvedTheme } = useTheme()
    const currentTheme = resolvedTheme || theme || 'light'
    const isSelectionMode = activeTool === 'mouse'
    const lastClickRef = useRef<number>(0)
    const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null)
    
    // Ref para acesso atualizado aos widgets dentro dos event listeners
    const widgetsRef = useRef(widgets)
    useEffect(() => {
        widgetsRef.current = widgets
    }, [widgets])

    // Save canvas settings to backend with debounce
    useEffect(() => {
        if (!currentDashboard?.id) return
        
        // Clear existing timeout
        if (saveTimeoutRef.current) {
            clearTimeout(saveTimeoutRef.current)
        }
        
        // Set new timeout to save after 1 second of inactivity
        saveTimeoutRef.current = setTimeout(async () => {
            try {
                await updateDashboard(currentDashboard.id, {
                    canvas_settings: {
                        scale,
                        position,
                        snapToGrid,
                        gridSize,
                    },
                })
            } catch (error) {
                console.error('Error saving canvas settings:', error)
            }
        }, 1000)
        
        return () => {
            if (saveTimeoutRef.current) {
                clearTimeout(saveTimeoutRef.current)
            }
        }
    }, [scale, position, snapToGrid, gridSize, currentDashboard?.id, updateDashboard])

    const handleWheel = (e: React.WheelEvent) => {
        if (e.ctrlKey || e.metaKey) {
            e.preventDefault()
            if (e.deltaY < 0) zoomIn()
            else zoomOut()
        } else {
            // Pan with wheel
            setPosition({
                x: position.x - e.deltaX,
                y: position.y - e.deltaY
            })
        }
    }

    useEffect(() => {
        if (isSidebarOpen) return // Don't set up pan when sidebar is open

        const handleGlobalMouseMove = (e: MouseEvent) => {
            // Handle canvas panning
            if (!isDragging || !dragStartRef.current) return
            
            const deltaX = e.clientX - dragStartRef.current.x
            const deltaY = e.clientY - dragStartRef.current.y
            
            setPosition({
                x: dragStartRef.current.startPosition.x + deltaX,
                y: dragStartRef.current.startPosition.y + deltaY
            })
        }

        const handleGlobalMouseUp = (e: MouseEvent) => {
            if (isDragging) {
                setIsDragging(false)
                dragStartRef.current = null
            }
        }
        
        if (isDragging) {
            window.addEventListener('mousemove', handleGlobalMouseMove, { passive: true })
            window.addEventListener('mouseup', handleGlobalMouseUp)
        }

        return () => {
            window.removeEventListener('mousemove', handleGlobalMouseMove)
            window.removeEventListener('mouseup', handleGlobalMouseUp)
        }
    }, [isDragging, position, setPosition, isSidebarOpen, scale])
    
    // Clear selection state when selection mode is deactivated
    const prevSelectionModeRef = useRef(isSelectionMode)
    useEffect(() => {
        // Only clear if transitioning from active to inactive
        if (prevSelectionModeRef.current && !isSelectionMode) {
            // Clear selection box
            setSelectionBox(null)
            // Clear selected widgets
            selectWidgets([])
            selectWidget(null)
        }
        prevSelectionModeRef.current = isSelectionMode
    }, [isSelectionMode, selectWidgets, selectWidget])
    
    // Handle Backspace/Delete for multiple selection
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if ((e.key === 'Backspace' || e.key === 'Delete') && selectedWidgetIds.length > 0) {
                e.preventDefault()
                removeWidgets(selectedWidgetIds)
            }
        }
        
        window.addEventListener('keydown', handleKeyDown)
        return () => window.removeEventListener('keydown', handleKeyDown)
    }, [selectedWidgetIds, removeWidgets])

    return (
        <div
            data-tour="canvas"
            className={cn(
                "w-full h-full overflow-hidden bg-secondary/20 relative cursor-grab active:cursor-grabbing transition-all duration-300",
                isSidebarOpen && "pointer-events-none"
            )}
            onWheel={handleWheel}
            style={{ cursor: isSelectionMode ? 'crosshair' : (isDragging ? 'grabbing' : 'grab') }}
            data-selection-mode={isSelectionMode}
            onMouseDown={(e) => {
                // Don't start pan if sidebar is open
                if (isSidebarOpen) return

                const target = e.target as HTMLElement
                const isAISearchBar = target.closest('form') || target.closest('input') || target.closest('button[type="submit"]')
                const isControlButton = target.closest('button') && (target.closest('.absolute') || target.closest('[class*="z-50"]'))
                const isTextWidget = target.closest('.text-widget-editable') || target.closest('[data-text-widget]')
                const isRndWidget = target.closest('[class*="react-rnd"]')
                const isToolbar = target.closest('[data-text-toolbar]')
                const isWidgetActionButton = target.closest('.widget-action-button')
                const isCard = target.closest('[data-slot="card"]') || target.closest('[class*="card"]')
                const isWidgetContainer = target.closest('[class*="react-rnd"]') || target.closest('[data-widget-id]')

                // Handle Selection Mode
                if (activeTool === 'mouse') {
                    // If clicking on interactive elements, let them handle it
                    if (isAISearchBar || isControlButton || isTextWidget || isRndWidget || isToolbar || isWidgetActionButton || isCard || isWidgetContainer) {
                        return
                    }

                    e.preventDefault()
                    e.stopPropagation()

                    const canvasElement = e.currentTarget as HTMLElement
                    const gridContainer = canvasElement.querySelector('.canvas-grid') as HTMLElement
                    if (!gridContainer) return

                    const gridRect = gridContainer.getBoundingClientRect()
                    // Calculate start position in canvas coordinates
                    const startX = (e.clientX - gridRect.left - position.x) / scale
                    const startY = (e.clientY - gridRect.top - position.y) / scale
                    const startPoint = { x: startX, y: startY }

                    // Start selection box UI
                    setSelectionBox({ start: startPoint, end: startPoint })
                    // Clear previous selection
                    selectWidget(null)
                    selectWidgets([])

                    // Define move handler directly attached to window to avoid stale closures
                    const handleSelectionMove = (moveEvent: MouseEvent) => {
                        moveEvent.preventDefault()

                        const currentX = (moveEvent.clientX - gridRect.left - position.x) / scale
                        const currentY = (moveEvent.clientY - gridRect.top - position.y) / scale
                        const endPoint = { x: currentX, y: currentY }

                        // Update box UI
                        setSelectionBox({ start: startPoint, end: endPoint })

                        // Calculate selection intersection
                        const left = Math.min(startPoint.x, endPoint.x)
                        const top = Math.min(startPoint.y, endPoint.y)
                        const right = Math.max(startPoint.x, endPoint.x)
                        const bottom = Math.max(startPoint.y, endPoint.y)

                        // Use widgetsRef to access current widgets state
                        const selectedIds = widgetsRef.current
                            .filter((widget) => {
                                const widgetLeft = widget.position.x
                                const widgetTop = widget.position.y
                                const widgetRight = widget.position.x + widget.size.width
                                const widgetBottom = widget.position.y + widget.size.height

                                return widgetLeft < right && widgetRight > left && widgetTop < bottom && widgetBottom > top
                            })
                            .map((w) => w.id)

                        selectWidgets(selectedIds)
                    }

                    // Define up handler to cleanup
                    const handleSelectionUp = () => {
                        window.removeEventListener('mousemove', handleSelectionMove)
                        window.removeEventListener('mouseup', handleSelectionUp)
                        // Clear box but keep selection
                        setSelectionBox(null)
                    }

                    // Attach listeners
                    window.addEventListener('mousemove', handleSelectionMove)
                    window.addEventListener('mouseup', handleSelectionUp)

                    return
                }

                // If active tool is selected (creation mode), create widget at click position
                if (
                    activeTool &&
                    activeTool !== 'mouse' &&
                    !isAISearchBar &&
                    !isControlButton &&
                    !isTextWidget &&
                    !isRndWidget &&
                    !isToolbar &&
                    !isWidgetActionButton &&
                    !isCard &&
                    !isWidgetContainer
                ) {
                    e.preventDefault()
                    e.stopPropagation()

                    // Handle widget creation asynchronously
                    ;(async () => {
                        try {
                            // Ensure we have a dashboard before creating widgets
                            let dashboard = useDashboardStore.getState().currentDashboard
                            if (!dashboard) {
                                // Try to create a dashboard if we have a planet
                                if (currentPlanet) {
                                    console.log('[Canvas] Creating dashboard for planet:', currentPlanet.id)
                                    dashboard = await createDashboard({
                                        name: 'My Dashboard',
                                        planet_id: currentPlanet.id,
                                    })
                                    console.log('[Canvas] Dashboard created:', dashboard.id)
                                    // Wait a bit for the store to update
                                    await new Promise(resolve => setTimeout(resolve, 200))
                                    // Verify dashboard is set
                                    dashboard = useDashboardStore.getState().currentDashboard
                                    if (!dashboard) {
                                        console.error('[Canvas] Dashboard not set after creation')
                                        alert('Não foi possível criar um dashboard. Por favor, tente novamente.')
                                        setActiveTool(null)
                                        return
                                    }
                                } else {
                                    alert('Por favor, selecione ou crie um Planet primeiro.')
                                    setActiveTool(null)
                                    return
                                }
                            }

                            console.log('[Canvas] Creating widget with dashboard:', dashboard.id)

                            const canvasElement = e.currentTarget as HTMLElement
                            const gridContainer = canvasElement.querySelector('.canvas-grid') as HTMLElement
                            if (!gridContainer) {
                                console.error('[Canvas] Grid container not found')
                                return
                            }

                            const gridRect = gridContainer.getBoundingClientRect()
                            // Calculate position in canvas coordinates (accounting for transform and scale)
                            const clickX = (e.clientX - gridRect.left - position.x) / scale
                            const clickY = (e.clientY - gridRect.top - position.y) / scale

                            if (activeTool === 'text') {
                                const widgetWidth = 250
                                const widgetHeight = 80
                                // Combine existing widgets with pending widgets
                                const allWidgets = [
                                    ...widgets.map(w => ({ position: w.position, size: w.size })),
                                    ...pendingWidgets
                                ]
                                // Use grid positioning for initial placement
                                const finalPosition = findNextGridPosition(
                                    { width: widgetWidth, height: widgetHeight },
                                    allWidgets
                                )
                                
                                const newWidget = {
                                    type: 'text' as const,
                                    title: 'Text',
                                    position: finalPosition,
                                    size: { width: widgetWidth, height: widgetHeight },
                                    data: {
                                        content: '',
                                        fontFamily: 'Noto Sans',
                                        fontSize: 16,
                                        fontWeight: 'normal',
                                        textAlign: 'left',
                                        textColor: currentTheme === 'dark' ? '#ffffff' : '#000000',
                                    },
                                }
                                const widgetId = await addWidget(newWidget)
                                console.log('[Canvas] Text widget created:', widgetId)
                                setActiveTool(null)
                            } else if (activeTool === 'kpi') {
                            const widgetWidth = 250
                            const widgetHeight = 120
                            // Combine existing widgets with pending widgets
                            const allWidgets = [
                                ...widgets.map(w => ({ position: w.position, size: w.size })),
                                ...pendingWidgets
                            ]
                            // Use grid positioning for initial placement
                            const finalPosition = findNextGridPosition(
                                { width: widgetWidth, height: widgetHeight },
                                allWidgets
                            )
                            
                                const newWidget = {
                                    type: 'kpi' as const,
                                    title: 'KPI',
                                    position: finalPosition,
                                    size: { width: widgetWidth, height: widgetHeight },
                                    data: {
                                        value: '0',
                                        change: '0%',
                                        isPlaceholder: true,
                                    },
                                }
                                const widgetId = await addWidget(newWidget)
                                console.log('[Canvas] KPI widget created:', widgetId)
                                setActiveTool(null)
                            } else if (activeTool === 'table') {
                            const widgetWidth = 400
                            const widgetHeight = 250
                            // Combine existing widgets with pending widgets
                            const allWidgets = [
                                ...widgets.map(w => ({ position: w.position, size: w.size })),
                                ...pendingWidgets
                            ]
                            // Use grid positioning for initial placement
                            const finalPosition = findNextGridPosition(
                                { width: widgetWidth, height: widgetHeight },
                                allWidgets
                            )
                            
                                const newWidget = {
                                    type: 'table' as const,
                                    title: 'Table',
                                    position: finalPosition,
                                    size: { width: widgetWidth, height: widgetHeight },
                                    data: {
                                        value: '0',
                                        change: '0%',
                                        columns: ['Column 1', 'Column 2', 'Column 3'],
                                        rows: [],
                                    },
                                }
                                const widgetId = await addWidget(newWidget)
                                console.log('[Canvas] Table widget created:', widgetId)
                                setActiveTool(null)
                            } else if (activeTool.startsWith('chart-')) {
                                const chartType = activeTool.replace('chart-', '') as 'bar' | 'pie' | 'line' | 'scatter'
                                const widgetWidth = 320
                                const widgetHeight = 240
                                // Combine existing widgets with pending widgets
                                const allWidgets = [
                                    ...widgets.map(w => ({ position: w.position, size: w.size })),
                                    ...pendingWidgets
                                ]
                                // Use grid positioning for initial placement
                                const finalPosition = findNextGridPosition(
                                    { width: widgetWidth, height: widgetHeight },
                                    allWidgets
                                )
                                
                                const newWidget = {
                                    type: 'chart' as const,
                                    title: `${chartType.charAt(0).toUpperCase() + chartType.slice(1)} Chart`,
                                    position: finalPosition,
                                    size: { width: widgetWidth, height: widgetHeight },
                                    data: {
                                        type: chartType,
                                        series: [0, 0, 0, 0, 0],
                                        labels: ['A', 'B', 'C', 'D', 'E'],
                                        isPlaceholder: true,
                                    },
                                }
                                console.log('[Canvas] Creating chart widget:', newWidget)
                                const widgetId = await addWidget(newWidget)
                                console.log('[Canvas] Chart widget created successfully:', widgetId)
                                setActiveTool(null)
                            }
                        } catch (err) {
                            console.error('[Canvas] Error in widget creation flow:', err)
                            alert(`Erro ao criar widget: ${err instanceof Error ? err.message : 'Erro desconhecido'}`)
                            setActiveTool(null)
                        }
                    })()
                    return
                }

                // Only allow canvas pan if clicking on empty space (not on widgets, cards, or interactive elements)
                // Don't pan if in selection mode
                if (
                    !isSelectionMode &&
                    !isAISearchBar &&
                    !isControlButton &&
                    !isTextWidget &&
                    !isRndWidget &&
                    !isToolbar &&
                    !isWidgetActionButton &&
                    !isCard &&
                    !isWidgetContainer
                ) {
                    // Handle double click to open sidebar
                    const now = Date.now()
                    if (now - lastClickRef.current < 300) {
                        // Double click detected
                        setAIHistoryOpen(true)
                        lastClickRef.current = 0
                        return
                    }
                    lastClickRef.current = now

                    // Deselect widget when clicking on canvas
                    selectWidget(null)

                    dragStartRef.current = {
                        x: e.clientX,
                        y: e.clientY,
                        startPosition: { ...position },
                    }
                    setIsDragging(true)
                }
            }}
        >
            {/* Controls */}
            <Toolbar />
            <CanvasControls />
            <TextToolbarFloating />

            {/* AI Search Bar */}
            <AISearchBar />

            {/* Canvas Content */}
            <div
                ref={containerRef}
                className="canvas-grid w-full h-full origin-center will-change-transform"
                style={{
                    transform: `translate(${position.x}px, ${position.y}px) scale(${scale})`,
                }}
            >
                {/* Grid Pattern - Extended to allow free movement */}
                <div
                    className="absolute inset-[-5000%] pointer-events-none opacity-20"
                    style={{
                        backgroundImage: `radial-gradient(circle, currentColor 1px, transparent 1px)`,
                        backgroundSize: '24px 24px',
                    }}
                />

                {/* Widgets Layer - Extended container for infinite canvas */}
                <div 
                    className="relative" 
                    style={{ 
                        width: '500%', 
                        height: '500%',
                        overflow: 'visible', // Ensure widgets are not clipped
                        position: 'relative',
                        zIndex: 1
                    }}
                >
                    {children}
                </div>

                {/* Selection Box - Inside canvas transform */}
                {selectionBox && (
                    <SelectionBox start={selectionBox.start} end={selectionBox.end} visible={true} />
                )}

                {/* Connection Lines */}
                <svg className="absolute inset-0 pointer-events-none z-20" style={{ width: '500%', height: '500%' }}>
                    {connections.map((connection) => {
                        const fromWidget = widgets.find((w) => w.id === connection.from)
                        const toWidget = widgets.find((w) => w.id === connection.to)
                        if (!fromWidget || !toWidget) return null
                        return (
                            <ConnectionLine
                                key={connection.id}
                                connection={connection}
                                fromWidget={fromWidget}
                                toWidget={toWidget}
                                onDelete={() => {}}
                            />
                        )
                    })}
                </svg>
            </div>
        </div>
    )
}
