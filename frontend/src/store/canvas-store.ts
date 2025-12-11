import { create } from 'zustand'

interface CanvasState {
    scale: number
    position: { x: number; y: number }
    isDragging: boolean
    snapToGrid: boolean
    gridSize: number
    setScale: (scale: number) => void
    setPosition: (position: { x: number; y: number }) => void
    setIsDragging: (isDragging: boolean) => void
    setSnapToGrid: (snap: boolean) => void
    setGridSize: (size: number) => void
    zoomIn: () => void
    zoomOut: () => void
    resetView: () => void
    snapPosition: (x: number, y: number) => { x: number; y: number }
    getViewportCenter: () => { x: number; y: number }
    findVisiblePositionInViewport: (widgetSize: { width: number; height: number }, preferredPosition?: { x: number; y: number }, existingWidgets?: Array<{ position: { x: number; y: number }; size: { width: number; height: number } }>) => { x: number; y: number }
    findNextGridPosition: (widgetSize: { width: number; height: number }, existingWidgets?: Array<{ position: { x: number; y: number }; size: { width: number; height: number } }>) => { x: number; y: number }
    loadSettings: (settings: { scale?: number; position?: { x: number; y: number }; snapToGrid?: boolean; gridSize?: number }) => void
}

export const useCanvasStore = create<CanvasState>((set, get) => ({
    scale: 1,
    position: { x: 0, y: 0 },
    isDragging: false,
    snapToGrid: false,
    gridSize: 24,
    setScale: (scale) => set({ scale }),
    setPosition: (position) => set({ position }),
    setIsDragging: (isDragging) => set({ isDragging }),
    setSnapToGrid: (snap) => set({ snapToGrid: snap }),
    setGridSize: (size) => set({ gridSize: size }),
    zoomIn: () => set((state) => ({ scale: Math.min(state.scale + 0.1, 3) })),
    zoomOut: () => set((state) => ({ scale: Math.max(state.scale - 0.1, 0.2) })),
    resetView: () => set({ scale: 1, position: { x: 0, y: 0 } }),
    snapPosition: (x, y) => {
        const { snapToGrid, gridSize } = get()
        if (!snapToGrid) return { x, y }
        return {
            x: Math.round(x / gridSize) * gridSize,
            y: Math.round(y / gridSize) * gridSize,
        }
    },
    getViewportCenter: () => {
        const { position, scale } = get()
        // Centro do viewport visível
        const viewportCenterX = window.innerWidth / 2
        const viewportCenterY = window.innerHeight / 2
        
        // Converter coordenadas da tela para coordenadas do canvas
        // Fórmula inversa: canvas = (tela - position) / scale
        const canvasX = (viewportCenterX - position.x) / scale
        const canvasY = (viewportCenterY - position.y) / scale
        
        return { x: canvasX, y: canvasY }
    },
    findVisiblePositionInViewport: (widgetSize, preferredPosition, existingWidgets = []) => {
        const { position: canvasPosition, scale, snapPosition } = get()
        
        // Calculate visible viewport bounds in canvas coordinates
        const viewportLeft = -canvasPosition.x / scale
        const viewportTop = -canvasPosition.y / scale
        const viewportRight = (window.innerWidth - canvasPosition.x) / scale
        const viewportBottom = (window.innerHeight - canvasPosition.y) / scale
        
        // Account for topbar at top (fixed top-4 = 16px + ~50px height = ~66px total)
        const topbarHeight = 66 / scale
        const topbarTopMargin = topbarHeight + (20 / scale)
        
        // Account for topbar left section - fixed left-4, ~250px width
        const topbarLeftWidth = 250 / scale
        const topbarLeftMargin = topbarLeftWidth + (20 / scale)
        
        // Account for topbar right section - fixed right-4, ~200px width
        const topbarRightWidth = 200 / scale
        const topbarRightMargin = topbarRightWidth + (20 / scale)
        
        // Account for toolbar on left - fixed left-4, ~60px width
        const toolbarWidth = 60 / scale
        const toolbarLeftMargin = toolbarWidth + (20 / scale)
        
        // Account for chatbox at bottom
        const chatboxHeight = 80 / scale
        const usableBottom = viewportBottom - chatboxHeight
        
        // Widget dimensions in canvas coordinates
        const widgetWidth = widgetSize.width
        const widgetHeight = widgetSize.height
        
        // Margin between widgets
        const widgetMargin = 30 / scale
        const padding = 20 / scale
        
        // Calculate safe area bounds
        const safeTop = Math.max(viewportTop + topbarTopMargin, topbarTopMargin)
        const safeBottom = Math.min(usableBottom - widgetHeight - padding, viewportBottom - widgetHeight - padding)
        const safeLeft = Math.max(viewportLeft + Math.max(topbarLeftMargin, toolbarLeftMargin), Math.max(topbarLeftMargin, toolbarLeftMargin))
        const safeRight = Math.min(viewportRight - topbarRightMargin - widgetWidth - padding, viewportRight - widgetWidth - padding)
        
        // Check for overlaps with existing widgets (define before use)
        const checkOverlap = (x: number, y: number) => {
            return existingWidgets.some(widget => {
                const wx = widget.position.x
                const wy = widget.position.y
                const ww = widget.size.width
                const wh = widget.size.height
                
                const hasHorizontalOverlap = x + widgetWidth + widgetMargin > wx && x - widgetMargin < wx + ww
                const hasVerticalOverlap = y + widgetHeight + widgetMargin > wy && y - widgetMargin < wy + wh
                
                return hasHorizontalOverlap && hasVerticalOverlap
            })
        }
        
        // Check if preferred position is within visible bounds
        // Only use preferred position if it's FULLY within visible viewport AND safe area
        // This ensures widgets are never created outside the visible area
        if (preferredPosition) {
            const preferredX = preferredPosition.x - widgetWidth / 2
            const preferredY = preferredPosition.y - widgetHeight / 2
            
            // Check if preferred position is FULLY within visible viewport bounds
            const isFullyInViewport = (
                preferredX >= viewportLeft &&
                preferredX + widgetWidth <= viewportRight &&
                preferredY >= viewportTop &&
                preferredY + widgetHeight <= viewportBottom
            )
            
            // Check if preferred position is FULLY within safe bounds (no UI overlap)
            const isFullyInSafeArea = (
                preferredX >= safeLeft &&
                preferredX + widgetWidth <= safeRight &&
                preferredY >= safeTop &&
                preferredY + widgetHeight <= safeBottom
            )
            
            // Only use preferred position if it's FULLY visible and in safe area
            // AND doesn't overlap with existing widgets
            if (isFullyInViewport && isFullyInSafeArea) {
                const snapped = snapPosition(preferredX, preferredY)
                // Double check snapped position is still fully visible
                if (
                    snapped.x >= safeLeft &&
                    snapped.x + widgetWidth <= safeRight &&
                    snapped.y >= safeTop &&
                    snapped.y + widgetHeight <= safeBottom &&
                    !checkOverlap(snapped.x, snapped.y)
                ) {
                    return snapped
                }
            }
            // If preferred position is not fully visible, ignore it and use sequential placement
        }
        
        // Ensure all positions are within visible viewport bounds
        const clampToVisibleBounds = (x: number, y: number) => {
            let clampedX = Math.max(safeLeft, Math.min(x, safeRight - widgetWidth))
            let clampedY = Math.max(safeTop, Math.min(y, safeBottom - widgetHeight))
            return { x: clampedX, y: clampedY }
        }
        
        // Strategy 1: Sequential horizontal placement
        if (existingWidgets.length > 0) {
            // Find widgets in the current top row (same Y position, with tolerance)
            const topRowY = Math.min(...existingWidgets.map(w => w.position.y))
            const rowTolerance = widgetMargin * 2
            const topRowWidgets = existingWidgets.filter(w => 
                Math.abs(w.position.y - topRowY) < rowTolerance
            )
            
            if (topRowWidgets.length > 0) {
                // Find the rightmost widget in the current row
                const rightmostWidget = topRowWidgets.reduce((rightmost, widget) => {
                    const rightmostRight = rightmost.position.x + rightmost.size.width
                    const widgetRight = widget.position.x + widget.size.width
                    return widgetRight > rightmostRight ? widget : rightmost
                })
                
                // Try to place next to the rightmost widget in the same row
                const rightmostRight = rightmostWidget.position.x + rightmostWidget.size.width
                const tryX = rightmostRight + widgetMargin
                const tryY = rightmostWidget.position.y
                
                // Check if it fits horizontally in the current row
                if (
                    tryX + widgetWidth <= safeRight && 
                    tryY >= safeTop && 
                    tryY + widgetHeight <= safeBottom &&
                    tryX >= safeLeft
                ) {
                    const snappedX = snapPosition(tryX, tryY).x
                    const snappedY = snapPosition(tryX, tryY).y
                    
                    // Double check bounds after snapping - ensure fully visible
                    const clamped = clampToVisibleBounds(snappedX, snappedY)
                    if (
                        clamped.x >= safeLeft &&
                        clamped.x + widgetWidth <= safeRight &&
                        clamped.y >= safeTop &&
                        clamped.y + widgetHeight <= safeBottom &&
                        !checkOverlap(clamped.x, clamped.y)
                    ) {
                        return { x: clamped.x, y: clamped.y }
                    }
                }
                
                // Strategy 2: If doesn't fit in current row, start new row below
                // Find the tallest widget in the current row to determine new row Y
                const tallestWidget = topRowWidgets.reduce((tallest, widget) => {
                    return widget.size.height > tallest.size.height ? widget : tallest
                })
                
                const newRowY = tallestWidget.position.y + tallestWidget.size.height + widgetMargin
                
                // Start new row from the left (safeLeft)
                if (newRowY + widgetHeight <= safeBottom && newRowY >= safeTop) {
                    const snappedX = snapPosition(safeLeft, newRowY).x
                    const snappedY = snapPosition(safeLeft, newRowY).y
                    
                    // Double check bounds after snapping - ensure fully visible
                    const clamped = clampToVisibleBounds(snappedX, snappedY)
                    if (
                        clamped.x >= safeLeft &&
                        clamped.x + widgetWidth <= safeRight &&
                        clamped.y >= safeTop &&
                        clamped.y + widgetHeight <= safeBottom &&
                        !checkOverlap(clamped.x, clamped.y)
                    ) {
                        return { x: clamped.x, y: clamped.y }
                    }
                }
            }
        }
        
        // Strategy 3: If no widgets exist or strategies failed, start from top-left
        // For first widget, always start at top-left of safe area
        if (existingWidgets.length === 0) {
            const snappedX = snapPosition(safeLeft, safeTop).x
            const snappedY = snapPosition(safeLeft, safeTop).y
            
            // Verify position is within bounds after snapping - ensure fully visible
            const clamped = clampToVisibleBounds(snappedX, snappedY)
            if (
                clamped.x >= safeLeft &&
                clamped.x + widgetWidth <= safeRight &&
                clamped.y >= safeTop &&
                clamped.y + widgetHeight <= safeBottom
            ) {
                return { x: clamped.x, y: clamped.y }
            }
        }
        
        // Strategy 4: Find first available position from top-left, moving right and down
        // Use smaller steps for more precise positioning
        const stepY = Math.max(30 / scale, widgetHeight / 2)
        const stepX = Math.max(30 / scale, widgetWidth / 2)
        
        for (let y = safeTop; y <= safeBottom - widgetHeight; y += stepY) {
            for (let x = safeLeft; x <= safeRight - widgetWidth; x += stepX) {
                const snappedX = snapPosition(x, y).x
                const snappedY = snapPosition(x, y).y
                
                // Verify position is still within bounds after snapping - ensure fully visible
                const clamped = clampToVisibleBounds(snappedX, snappedY)
                if (
                    clamped.x >= safeLeft &&
                    clamped.x + widgetWidth <= safeRight &&
                    clamped.y >= safeTop &&
                    clamped.y + widgetHeight <= safeBottom &&
                    !checkOverlap(clamped.x, clamped.y)
                ) {
                    return { x: clamped.x, y: clamped.y }
                }
            }
        }
        
        // Fallback: top-left of safe visible area (ensures visibility)
        // Always clamp to ensure it's within visible bounds
        const fallbackX = Math.max(safeLeft, Math.min(safeLeft, safeRight - widgetWidth))
        const fallbackY = Math.max(safeTop, Math.min(safeTop, safeBottom - widgetHeight))
        const snapped = snapPosition(fallbackX, fallbackY)
        const clamped = clampToVisibleBounds(snapped.x, snapped.y)
        return clamped
    },
    findNextGridPosition: (widgetSize, existingWidgets = []) => {
        const { position: canvasPosition, scale, snapPosition } = get()
        
        console.log(`[Grid] 🎯 Finding position for widget ${widgetSize.width}x${widgetSize.height}, existing widgets: ${existingWidgets.length}`)
        
        // Grid configuration
        const CELL_SIZE_SCREEN = 4 // 4px cells in screen coordinates
        const TOOLBAR_WIDTH = 60
        const TOPBAR_HEIGHT = 66
        const GRID_OFFSET_LEFT = TOOLBAR_WIDTH + 10
        const GRID_OFFSET_TOP = TOPBAR_HEIGHT + 5
        const WIDGET_MARGIN = 20 / scale // Margin between widgets in canvas coordinates
        
        // Grid origin in screen coordinates (fixed)
        const gridOriginScreenX = GRID_OFFSET_LEFT
        const gridOriginScreenY = GRID_OFFSET_TOP
        
        // Convert to canvas coordinates
        const gridOriginX = (gridOriginScreenX - canvasPosition.x) / scale
        const gridOriginY = (gridOriginScreenY - canvasPosition.y) / scale
        
        // Cell size in canvas coordinates
        const cellSize = CELL_SIZE_SCREEN / scale
        
        // Viewport bounds in canvas coordinates
        const viewportLeft = -canvasPosition.x / scale
        const viewportTop = -canvasPosition.y / scale
        const viewportRight = (window.innerWidth - canvasPosition.x) / scale
        const chatboxHeight = 80
        const chatboxBottomScreen = window.innerHeight - chatboxHeight
        const viewportBottom = (chatboxBottomScreen - canvasPosition.y) / scale
        
        // Safe area (accounting for UI elements)
        const safeLeft = Math.max(viewportLeft, gridOriginX)
        const safeTop = Math.max(viewportTop, gridOriginY)
        const safeRight = Math.min(viewportRight, viewportRight - 20 / scale)
        const safeBottom = Math.min(viewportBottom, viewportBottom - 20 / scale)
        
        // Helper: Check if two rectangles overlap (with margin)
        const checkOverlap = (x1: number, y1: number, w1: number, h1: number, 
                             x2: number, y2: number, w2: number, h2: number): boolean => {
            return !(x1 + w1 + WIDGET_MARGIN <= x2 || 
                    x2 + w2 + WIDGET_MARGIN <= x1 || 
                    y1 + h1 + WIDGET_MARGIN <= y2 || 
                    y2 + h2 + WIDGET_MARGIN <= y1)
        }
        
        // Helper: Check if position is valid (no overlap, within viewport)
        const isValidPosition = (x: number, y: number): boolean => {
            // Check bounds
            if (x < safeLeft || y < safeTop || 
                x + widgetSize.width > safeRight || 
                y + widgetSize.height > safeBottom) {
                return false
            }
            
            // Check overlap with existing widgets
            for (const widget of existingWidgets) {
                if (checkOverlap(
                    x, y, widgetSize.width, widgetSize.height,
                    widget.position.x, widget.position.y, widget.size.width, widget.size.height
                )) {
                    return false
                }
            }
            
            return true
        }
        
        // Helper: Snap position to grid
        const snapToGrid = (x: number, y: number) => {
            const snappedX = Math.round(x / cellSize) * cellSize
            const snappedY = Math.round(y / cellSize) * cellSize
            return { x: snappedX, y: snappedY }
        }
        
        // Strategy 1: First widget - place at top-left of safe area
        if (existingWidgets.length === 0) {
            const position = snapToGrid(safeLeft, safeTop)
            if (isValidPosition(position.x, position.y)) {
                console.log(`[Grid] ✅ First widget at (${position.x.toFixed(1)}, ${position.y.toFixed(1)})`)
                return position
            }
        }
        
        // Strategy 2: Find rightmost widget and place next to it
        if (existingWidgets.length > 0) {
            // Find the widget with the highest right edge (X + width)
            const rightmostWidget = existingWidgets.reduce((rightmost, widget) => {
                const rightmostRight = rightmost.position.x + rightmost.size.width
                const currentRight = widget.position.x + widget.size.width
                return currentRight > rightmostRight ? widget : rightmost
            })
            
            const rightmostRight = rightmostWidget.position.x + rightmostWidget.size.width
            const rightmostY = rightmostWidget.position.y
            const rightmostBottom = rightmostWidget.position.y + rightmostWidget.size.height
            
            // Try placing to the right of the rightmost widget
            const tryX = rightmostRight + WIDGET_MARGIN
            const tryY = rightmostY
            const snapped = snapToGrid(tryX, tryY)
            
            if (isValidPosition(snapped.x, snapped.y)) {
                console.log(`[Grid] ✅ Widget placed next to rightmost at (${snapped.x.toFixed(1)}, ${snapped.y.toFixed(1)})`)
                return snapped
            }
            
            // Strategy 3: If doesn't fit to the right, start new row below
            // Find tallest widget in the current "row" (similar Y positions)
            const rowTolerance = 50 / scale // Consider widgets within 50px as same row
            const sameRowWidgets = existingWidgets.filter(w => 
                Math.abs(w.position.y - rightmostY) < rowTolerance
            )
            
            const tallestWidget = sameRowWidgets.reduce((tallest, widget) => 
                widget.size.height > tallest.size.height ? widget : tallest
            )
            
            const newRowY = tallestWidget.position.y + tallestWidget.size.height + WIDGET_MARGIN
            const newRowX = safeLeft
            const newRowSnapped = snapToGrid(newRowX, newRowY)
            
            if (isValidPosition(newRowSnapped.x, newRowSnapped.y)) {
                console.log(`[Grid] ✅ Widget placed in new row at (${newRowSnapped.x.toFixed(1)}, ${newRowSnapped.y.toFixed(1)})`)
                return newRowSnapped
            }
        }
        
        // Strategy 4: Fallback - scan from top-left, left to right, top to bottom
        const stepX = Math.max(cellSize, widgetSize.width / 4)
        const stepY = Math.max(cellSize, widgetSize.height / 4)
        
        for (let y = safeTop; y <= safeBottom - widgetSize.height; y += stepY) {
            for (let x = safeLeft; x <= safeRight - widgetSize.width; x += stepX) {
                const snapped = snapToGrid(x, y)
                if (isValidPosition(snapped.x, snapped.y)) {
                    console.log(`[Grid] ✅ Widget placed (fallback scan) at (${snapped.x.toFixed(1)}, ${snapped.y.toFixed(1)})`)
                    return snapped
                }
            }
        }
        
        // Final fallback: Use findVisiblePositionInViewport
        console.log(`[Grid] ⚠️ Using findVisiblePositionInViewport as last resort`)
        const fallback = get().findVisiblePositionInViewport(widgetSize, undefined, existingWidgets)
        console.log(`[Grid] ✅ Final fallback position: (${fallback.x.toFixed(1)}, ${fallback.y.toFixed(1)})`)
        return fallback
    },
    loadSettings: (settings) => {
        set({
            scale: settings.scale ?? 1,
            position: settings.position ?? { x: 0, y: 0 },
            snapToGrid: settings.snapToGrid ?? false,
            gridSize: settings.gridSize ?? 24,
        })
    },
}))
