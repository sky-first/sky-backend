"use client"

import { useRef } from "react"
import { Image } from "lucide-react"
import { cn } from "@/lib/utils"
import { useTheme } from "next-themes"

interface ToolbarUploadButtonProps {
    onUpload: (files: FileList) => void
    accept?: string
    multiple?: boolean
}

export function ToolbarUploadButton({ 
    onUpload, 
    accept = ".csv,.xlsx,.xls,.png,.jpg,.jpeg,.pdf",
    multiple = true 
}: ToolbarUploadButtonProps) {
    const fileInputRef = useRef<HTMLInputElement>(null)
    const { resolvedTheme } = useTheme()
    const isDark = resolvedTheme === 'dark'

    const handleClick = () => {
        fileInputRef.current?.click()
    }

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = e.target.files
        if (files && files.length > 0) {
            onUpload(files)
        }
        // Reset input to allow selecting the same file again
        if (fileInputRef.current) {
            fileInputRef.current.value = ''
        }
    }

    return (
        <>
            <input
                ref={fileInputRef}
                type="file"
                accept={accept}
                multiple={multiple}
                onChange={handleFileChange}
                className="hidden"
            />
            <button
                onClick={handleClick}
                className={cn(
                    "h-10 w-10 rounded-lg transition-all duration-200",
                    "flex items-center justify-center",
                    "hover:bg-accent active:scale-95",
                    isDark
                        ? "text-white/90 hover:bg-white/8 active:bg-white/12"
                        : "text-gray-900 hover:bg-black/5 active:bg-black/10"
                )}
                aria-label="Upload files"
            >
                <Image className="w-5 h-5" />
            </button>
        </>
    )
}

