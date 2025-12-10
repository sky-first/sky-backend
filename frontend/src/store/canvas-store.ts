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
    loadSettings: (settings) => {
        set({
            scale: settings.scale ?? 1,
            position: settings.position ?? { x: 0, y: 0 },
            snapToGrid: settings.snapToGrid ?? false,
            gridSize: settings.gridSize ?? 24,
        })
    },
}))
