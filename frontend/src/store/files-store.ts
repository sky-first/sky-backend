import { create } from 'zustand'
import {
  filesApi,
  type FileUpload,
  type FileUploadResponse,
  type CSVUploadResponse,
  type ExcelUploadResponse,
} from '@/lib/api/files'

export interface FilesState {
  files: FileUpload[]
  isLoading: boolean
  error: string | null
  uploadProgress: Record<string, number> // file name -> progress percentage

  // Actions
  uploadFile: (
    file: File | Blob,
    widgetId?: string,
    onProgress?: (progress: number) => void
  ) => Promise<FileUploadResponse>
  uploadCSV: (
    file: File | Blob,
    onProgress?: (progress: number) => void
  ) => Promise<CSVUploadResponse>
  uploadExcel: (
    file: File | Blob,
    onProgress?: (progress: number) => void
  ) => Promise<ExcelUploadResponse>
  uploadImage: (
    file: File | Blob,
    widgetId?: string,
    onProgress?: (progress: number) => void
  ) => Promise<FileUploadResponse>
  uploadPDF: (
    file: File | Blob,
    widgetId?: string,
    onProgress?: (progress: number) => void
  ) => Promise<FileUploadResponse>
  fetchFile: (fileId: string) => Promise<FileUpload>
  deleteFile: (fileId: string) => Promise<void>
  getFileDownloadUrl: (fileId: string) => Promise<string>
  clearError: () => void
}

export const useFilesStore = create<FilesState>()((set, get) => ({
  files: [],
  isLoading: false,
  error: null,
  uploadProgress: {},

  uploadFile: async (file, widgetId, onProgress) => {
    set({ isLoading: true, error: null })
    const fileName = file instanceof File ? file.name : 'file'

    try {
      const progressHandler = onProgress
        ? (progress: number) => {
            set((state) => ({
              uploadProgress: {
                ...state.uploadProgress,
                [fileName]: progress,
              },
            }))
            onProgress(progress)
          }
        : undefined

      const response = await filesApi.uploadFile(file, widgetId, progressHandler)

      // Fetch full file info and add to list
      const fileInfo = await filesApi.getFile(response.file_id)
      set((state) => ({
        files: [...state.files, fileInfo],
        uploadProgress: {
          ...state.uploadProgress,
          [fileName]: 100,
        },
        isLoading: false,
      }))

      // Clear progress after a delay
      setTimeout(() => {
        set((state) => {
          const newProgress = { ...state.uploadProgress }
          delete newProgress[fileName]
          return { uploadProgress: newProgress }
        })
      }, 1000)

      return response
    } catch (error) {
      console.error('Error uploading file:', error)
      set((state) => {
        const newProgress = { ...state.uploadProgress }
        delete newProgress[fileName]
        return {
          error: error instanceof Error ? error.message : 'Failed to upload file',
          isLoading: false,
          uploadProgress: newProgress,
        }
      })
      throw error
    }
  },

  uploadCSV: async (file, onProgress) => {
    set({ isLoading: true, error: null })
    const fileName = file instanceof File ? file.name : 'file'

    try {
      const progressHandler = onProgress
        ? (progress: number) => {
            set((state) => ({
              uploadProgress: {
                ...state.uploadProgress,
                [fileName]: progress,
              },
            }))
            onProgress(progress)
          }
        : undefined

      const response = await filesApi.uploadCSV(file, progressHandler)

      // Fetch full file info and add to list
      const fileInfo = await filesApi.getFile(response.file_id)
      set((state) => ({
        files: [...state.files, fileInfo],
        uploadProgress: {
          ...state.uploadProgress,
          [fileName]: 100,
        },
        isLoading: false,
      }))

      // Clear progress after a delay
      setTimeout(() => {
        set((state) => {
          const newProgress = { ...state.uploadProgress }
          delete newProgress[fileName]
          return { uploadProgress: newProgress }
        })
      }, 1000)

      return response
    } catch (error) {
      console.error('Error uploading CSV:', error)
      set((state) => {
        const newProgress = { ...state.uploadProgress }
        delete newProgress[fileName]
        return {
          error: error instanceof Error ? error.message : 'Failed to upload CSV',
          isLoading: false,
          uploadProgress: newProgress,
        }
      })
      throw error
    }
  },

  uploadExcel: async (file, onProgress) => {
    set({ isLoading: true, error: null })
    const fileName = file instanceof File ? file.name : 'file'

    try {
      const progressHandler = onProgress
        ? (progress: number) => {
            set((state) => ({
              uploadProgress: {
                ...state.uploadProgress,
                [fileName]: progress,
              },
            }))
            onProgress(progress)
          }
        : undefined

      const response = await filesApi.uploadExcel(file, progressHandler)

      // Fetch full file info and add to list
      const fileInfo = await filesApi.getFile(response.file_id)
      set((state) => ({
        files: [...state.files, fileInfo],
        uploadProgress: {
          ...state.uploadProgress,
          [fileName]: 100,
        },
        isLoading: false,
      }))

      // Clear progress after a delay
      setTimeout(() => {
        set((state) => {
          const newProgress = { ...state.uploadProgress }
          delete newProgress[fileName]
          return { uploadProgress: newProgress }
        })
      }, 1000)

      return response
    } catch (error) {
      console.error('Error uploading Excel:', error)
      set((state) => {
        const newProgress = { ...state.uploadProgress }
        delete newProgress[fileName]
        return {
          error: error instanceof Error ? error.message : 'Failed to upload Excel',
          isLoading: false,
          uploadProgress: newProgress,
        }
      })
      throw error
    }
  },

  uploadImage: async (file, widgetId, onProgress) => {
    set({ isLoading: true, error: null })
    const fileName = file instanceof File ? file.name : 'file'

    try {
      const progressHandler = onProgress
        ? (progress: number) => {
            set((state) => ({
              uploadProgress: {
                ...state.uploadProgress,
                [fileName]: progress,
              },
            }))
            onProgress(progress)
          }
        : undefined

      const response = await filesApi.uploadImage(file, widgetId, progressHandler)

      // Fetch full file info and add to list
      const fileInfo = await filesApi.getFile(response.file_id)
      set((state) => ({
        files: [...state.files, fileInfo],
        uploadProgress: {
          ...state.uploadProgress,
          [fileName]: 100,
        },
        isLoading: false,
      }))

      // Clear progress after a delay
      setTimeout(() => {
        set((state) => {
          const newProgress = { ...state.uploadProgress }
          delete newProgress[fileName]
          return { uploadProgress: newProgress }
        })
      }, 1000)

      return response
    } catch (error) {
      console.error('Error uploading image:', error)
      set((state) => {
        const newProgress = { ...state.uploadProgress }
        delete newProgress[fileName]
        return {
          error: error instanceof Error ? error.message : 'Failed to upload image',
          isLoading: false,
          uploadProgress: newProgress,
        }
      })
      throw error
    }
  },

  uploadPDF: async (file, widgetId, onProgress) => {
    set({ isLoading: true, error: null })
    const fileName = file instanceof File ? file.name : 'file'

    try {
      const progressHandler = onProgress
        ? (progress: number) => {
            set((state) => ({
              uploadProgress: {
                ...state.uploadProgress,
                [fileName]: progress,
              },
            }))
            onProgress(progress)
          }
        : undefined

      const response = await filesApi.uploadPDF(file, widgetId, progressHandler)

      // Fetch full file info and add to list
      const fileInfo = await filesApi.getFile(response.file_id)
      set((state) => ({
        files: [...state.files, fileInfo],
        uploadProgress: {
          ...state.uploadProgress,
          [fileName]: 100,
        },
        isLoading: false,
      }))

      // Clear progress after a delay
      setTimeout(() => {
        set((state) => {
          const newProgress = { ...state.uploadProgress }
          delete newProgress[fileName]
          return { uploadProgress: newProgress }
        })
      }, 1000)

      return response
    } catch (error) {
      console.error('Error uploading PDF:', error)
      set((state) => {
        const newProgress = { ...state.uploadProgress }
        delete newProgress[fileName]
        return {
          error: error instanceof Error ? error.message : 'Failed to upload PDF',
          isLoading: false,
          uploadProgress: newProgress,
        }
      })
      throw error
    }
  },

  fetchFile: async (fileId) => {
    set({ isLoading: true, error: null })
    try {
      const file = await filesApi.getFile(fileId)
      set((state) => ({
        files: state.files.some((f) => f.id === fileId)
          ? state.files.map((f) => (f.id === fileId ? file : f))
          : [...state.files, file],
        isLoading: false,
      }))
      return file
    } catch (error) {
      console.error('Error fetching file:', error)
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch file',
        isLoading: false,
      })
      throw error
    }
  },

  deleteFile: async (fileId) => {
    set({ isLoading: true, error: null })
    try {
      await filesApi.deleteFile(fileId)
      set((state) => ({
        files: state.files.filter((f) => f.id !== fileId),
        isLoading: false,
      }))
    } catch (error) {
      console.error('Error deleting file:', error)
      set({
        error: error instanceof Error ? error.message : 'Failed to delete file',
        isLoading: false,
      })
      throw error
    }
  },

  getFileDownloadUrl: async (fileId) => {
    try {
      return await filesApi.getFileDownloadUrl(fileId)
    } catch (error) {
      console.error('Error getting file download URL:', error)
      throw error
    }
  },

  clearError: () => {
    set({ error: null })
  },
}))

