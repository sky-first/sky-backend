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
    loadSettings: (settings) => {
        set({
            scale: settings.scale ?? 1,
            position: settings.position ?? { x: 0, y: 0 },
            snapToGrid: settings.snapToGrid ?? false,
            gridSize: settings.gridSize ?? 24,
        })
    },
}))
