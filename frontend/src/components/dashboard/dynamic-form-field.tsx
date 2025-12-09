"use client"

import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { ConnectorField } from "@/lib/connectors/connector-registry"
import { Info } from "lucide-react"

interface DynamicFormFieldProps {
  field: ConnectorField
  value: any
  onChange: (value: any) => void
  isDark: boolean
  showConditional?: boolean
}

export function DynamicFormField({ field, value, onChange, isDark, showConditional = true }: DynamicFormFieldProps) {
  // Check if field should be shown based on conditional logic
  if (field.conditional && !showConditional) {
    return null
  }

  const renderField = () => {
    switch (field.type) {
      case 'text':
      case 'url':
        return (
          <Input
            type={field.type === 'url' ? 'url' : 'text'}
            value={value || ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder={field.placeholder}
            required={field.required}
            className={cn(
              "h-9 text-xs",
              isDark 
                ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
            )}
          />
        )
      
      case 'password':
        return (
          <Input
            type="password"
            value={value || ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder={field.placeholder}
            required={field.required}
            className={cn(
              "h-9 text-xs",
              isDark 
                ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
            )}
          />
        )
      
      case 'number':
        return (
          <Input
            type="number"
            value={value || ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder={field.placeholder}
            required={field.required}
            min={field.validation?.min}
            max={field.validation?.max}
            className={cn(
              "h-9 text-xs",
              isDark 
                ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
            )}
          />
        )
      
      case 'select':
        return (
          <div className="relative">
            <select
              value={value || ''}
              onChange={(e) => onChange(e.target.value)}
              required={field.required}
              className={cn(
                "h-9 w-full px-3 pr-8 rounded-lg text-xs border appearance-none cursor-pointer",
                isDark 
                  ? "bg-white/4 border-white/8 text-foreground" 
                  : "bg-white border-black/8 text-foreground"
              )}
            >
              {field.placeholder && <option value="">{field.placeholder}</option>}
              {field.options?.map(option => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <svg
              className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        )
      
      case 'textarea':
        return (
          <textarea
            value={value || ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder={field.placeholder}
            required={field.required}
            rows={3}
            className={cn(
              "w-full rounded-lg text-xs p-2.5 resize-none",
              isDark 
                ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
            )}
          />
        )
      
      case 'json':
        return (
          <textarea
            value={value || ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder={field.placeholder || 'Paste your JSON here'}
            required={field.required}
            rows={6}
            className={cn(
              "w-full rounded-lg text-xs p-2.5 resize-none font-mono",
              isDark 
                ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
            )}
          />
        )
      
      default:
        return null
    }
  }

  return (
    <div>
      <label className="text-xs font-medium text-foreground mb-1.5 block">
        {field.label}
        {field.required && <span className="text-red-500 ml-1">*</span>}
      </label>
      {field.description && (
        <div className="flex items-start gap-1 mb-1.5">
          <Info className="w-3 h-3 text-muted-foreground mt-0.5 flex-shrink-0" />
          <p className="text-[10px] text-muted-foreground leading-relaxed">{field.description}</p>
        </div>
      )}
      {renderField()}
    </div>
  )
}

