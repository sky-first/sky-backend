"use client"

import React, { useState, useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { 
    X, Search, Database, Shield, Users, Plus, Eye, Trash2, Edit2, 
    ChevronLeft, ChevronRight, RefreshCw, ArrowUpDown, 
    CheckCircle2, ChevronDown, UserPlus, Clock, Info, Settings,
    Crown, Navigation, Compass, User, MoreHorizontal, Server, Key, Link2,
    FileText, Globe, AlertCircle, Table
} from "lucide-react"
import { Input } from "@/components/ui/input"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { 
    CONNECTOR_REGISTRY, 
    getConnectorById, 
    getConnectorsByCategory,
    ConnectorDefinition 
} from "@/lib/connectors/connector-registry"
import { DataConnection, ConnectionMetadata, Space as ConnectionSpace, Crew, CrewMember as ConnectionCrewMember, ConnectionPermission } from "@/lib/types/connections"

// Icon mapping for connectors from backend
const iconMap: Record<string, typeof Database> = {
    database: Database,
    "file-spreadsheet": FileText,
    globe: Globe,
}
import { DynamicFormField } from "./dynamic-form-field"
import { connectionsApi, type Connection } from "@/lib/api/connections"
import { connectorsApi } from "@/lib/api/connectors"
import { useConnectorsStore } from "@/store/connectors-store"
import { permissionsApi, type ConnectionPermission as ApiConnectionPermission, type ConnectionPermissionCreate, type TableMemberPermission, type TableMemberPermissionCreate, type TableMemberPermissionUpdate } from "@/lib/api/permissions"
import { spacesApi, type Space, type SpaceTable } from "@/lib/api/spaces"
import { crewsApi, type Crew as ApiCrew, type CrewMember as ApiCrewMember } from "@/lib/api/crews"
import { usersApi, type User as ApiUser } from "@/lib/api/users"
import { useSpaceStore } from "@/store/space-store"
import { useCrewStore } from "@/store/crew-store"
import { colorNameToHex } from "@/lib/utils/planet-colors"

// ============================================
// ACTIONS DROPDOWN COMPONENT
// ============================================
interface ActionsDropdownProps {
    isOpen: boolean
    onClose: () => void
    onEdit: () => void
    onDelete: () => void
    onPermissions?: () => void
    onTables?: () => void
    onDiscoverTables?: () => void
    buttonRef: React.RefObject<HTMLButtonElement>
    isDark: boolean
}

function ActionsDropdown({ isOpen, onClose, onEdit, onDelete, onPermissions, onTables, onDiscoverTables, buttonRef, isDark }: ActionsDropdownProps) {
    const dropdownRef = useRef<HTMLDivElement>(null)
    
    useEffect(() => {
        if (!isOpen) return
        
        const handleClickOutside = (e: MouseEvent) => {
            const target = e.target as Node
            if (
                buttonRef.current && 
                !buttonRef.current.contains(target) &&
                dropdownRef.current &&
                !dropdownRef.current.contains(target)
            ) {
                onClose()
            }
        }
        
        const handleEscape = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                onClose()
            }
        }
        
        // Use capture phase to catch events before they bubble
        document.addEventListener('mousedown', handleClickOutside, true)
        document.addEventListener('keydown', handleEscape)
        
        return () => {
            document.removeEventListener('mousedown', handleClickOutside, true)
            document.removeEventListener('keydown', handleEscape)
        }
    }, [isOpen, onClose, buttonRef])
    
    if (!isOpen) return null
    
    return (
        <>
            <div 
                className="fixed inset-0 z-40" 
                onClick={onClose}
            />
            <div
                ref={dropdownRef}
                className={cn(
                    "absolute z-50 min-w-[120px] rounded-lg border shadow-lg",
                    "bg-white dark:bg-gray-800",
                    "border-gray-200 dark:border-gray-700",
                    "py-1",
                    "top-full right-0 mt-1"
                )}
            >
                {onTables && (
                    <button
                        onClick={() => {
                            onTables()
                            onClose()
                        }}
                        className={cn(
                            "w-full px-3 py-2 text-left text-xs hover:bg-gray-100 dark:hover:bg-gray-700",
                            "flex items-center gap-2 transition-colors"
                        )}
                    >
                        <Table className="w-3.5 h-3.5" />
                        Tables
                    </button>
                )}
                {onDiscoverTables && (
                    <button
                        onClick={() => {
                            onDiscoverTables()
                            onClose()
                        }}
                        className={cn(
                            "w-full px-3 py-2 text-left text-xs hover:bg-gray-100 dark:hover:bg-gray-700",
                            "flex items-center gap-2 transition-colors"
                        )}
                    >
                        <RefreshCw className="w-3.5 h-3.5" />
                        Discover tables
                    </button>
                )}
                <button
                    onClick={() => {
                        onEdit()
                        onClose()
                    }}
                    className={cn(
                        "w-full px-3 py-2 text-left text-xs hover:bg-gray-100 dark:hover:bg-gray-700",
                        "flex items-center gap-2 transition-colors"
                    )}
                >
                    <Edit2 className="w-3.5 h-3.5" />
                    Edit
                </button>
                {onPermissions && (
                    <button
                        onClick={() => {
                            onPermissions()
                            onClose()
                        }}
                        className={cn(
                            "w-full px-3 py-2 text-left text-xs hover:bg-gray-100 dark:hover:bg-gray-700",
                            "flex items-center gap-2 transition-colors"
                        )}
                    >
                        <Shield className="w-3.5 h-3.5" />
                        Permissions
                    </button>
                )}
                <button
                    onClick={() => {
                        onDelete()
                        onClose()
                    }}
                    className={cn(
                        "w-full px-3 py-2 text-left text-xs hover:bg-red-50 dark:hover:bg-red-900/20 text-red-500",
                        "flex items-center gap-2 transition-colors"
                    )}
                >
                    <Trash2 className="w-3.5 h-3.5" />
                    Delete
                </button>
            </div>
        </>
    )
}

// ============================================
// ASSIGN SPACE MODAL COMPONENT
// ============================================
interface AssignSpaceModalProps {
    isOpen: boolean
    onClose: () => void
    connectionId: string
    spaces: import("@/lib/api/spaces").Space[]
    connection: DataConnection | undefined
    onCreateSpace: (spaceData: { name: string; description: string; color: string }) => Promise<Space>
    onAssign: (connectionId: string, spaceId: string, accessLevel: string, selectedTables?: string[]) => Promise<void>
    onFinish: () => Promise<void>
    isDark: boolean
}

function AssignSpaceModal({
    isOpen,
    onClose,
    connectionId,
    spaces,
    connection,
    onCreateSpace,
    onAssign,
    onFinish,
    isDark
}: AssignSpaceModalProps) {
    const [showCreateSpace, setShowCreateSpace] = useState(spaces.length === 0)
    const [selectedSpaceId, setSelectedSpaceId] = useState<string>('')
    const [accessLevel, setAccessLevel] = useState<'full' | 'read-only' | 'custom'>('full')
    const [selectedTables, setSelectedTables] = useState<string[]>([])
    const [isSubmitting, setIsSubmitting] = useState(false)
    
    // Form para criar space
    const [newSpaceData, setNewSpaceData] = useState({
        name: '',
        description: '',
        color: 'blue'
    })
    const [isCreatingSpace, setIsCreatingSpace] = useState(false)
    
    const availableTables = connection?.metadata?.tables?.map(t => t.name) || []
    
    const handleCreateSpace = async () => {
        if (!newSpaceData.name.trim()) {
            alert('Please enter a space name')
            return
        }
        
        setIsCreatingSpace(true)
        try {
            const newSpace = await onCreateSpace(newSpaceData)
            // Após criar, usar esse space automaticamente
            setSelectedSpaceId(newSpace.id)
            setShowCreateSpace(false)
        } catch (error) {
            console.error('Error creating space:', error)
            alert('Failed to create space')
        } finally {
            setIsCreatingSpace(false)
        }
    }
    
    const handleAssign = async () => {
        if (!selectedSpaceId) {
            alert('Please select a space')
            return
        }
        
        if (accessLevel === 'custom' && selectedTables.length === 0) {
            alert('Please select at least one table for custom access')
            return
        }
        
        setIsSubmitting(true)
        try {
            await onAssign(connectionId, selectedSpaceId, accessLevel, accessLevel === 'custom' ? selectedTables : undefined)
            // Após atribuir, finalizar conexão
            await onFinish()
            onClose()
        } catch (error) {
            console.error('Error assigning space:', error)
            alert('Failed to assign space')
        } finally {
            setIsSubmitting(false)
        }
    }
    
    // Reset form when modal opens/closes
    useEffect(() => {
        if (isOpen) {
            setShowCreateSpace(spaces.length === 0)
            setSelectedSpaceId('')
            setAccessLevel('full')
            setSelectedTables([])
            setNewSpaceData({ name: '', description: '', color: 'blue' })
        }
    }, [isOpen, spaces.length])
    
    if (!isOpen) return null
    
    return (
        <>
            <div className="fixed inset-0 z-50 bg-black/50" onClick={onClose} />
            <div className={cn(
                "fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2",
                "w-full max-w-md rounded-lg border shadow-lg",
                "bg-white dark:bg-gray-800",
                "border-gray-200 dark:border-gray-700",
                "p-6"
            )}>
                <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold text-foreground">
                        {showCreateSpace ? 'Create Space' : 'Assign to Space'}
                    </h3>
                    <button onClick={onClose} className="p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-white/5">
                        <X className="w-4 h-4" />
                    </button>
                </div>
                
                {showCreateSpace ? (
                    // Form para criar space
                    <div className="space-y-4">
                        <div>
                            <label className="text-sm font-medium text-foreground mb-2 block">
                                Space Name <span className="text-red-500">*</span>
                            </label>
                            <Input
                                value={newSpaceData.name}
                                onChange={(e) => setNewSpaceData({ ...newSpaceData, name: e.target.value })}
                                placeholder="e.g., Marketing Data"
                                className={cn(
                                    "w-full",
                                    isDark 
                                        ? "bg-white/4 border-white/8" 
                                        : "bg-white border-black/8"
                                )}
                            />
                        </div>
                        
                        <div>
                            <label className="text-sm font-medium text-foreground mb-2 block">
                                Description
                            </label>
                            <textarea
                                value={newSpaceData.description}
                                onChange={(e) => setNewSpaceData({ ...newSpaceData, description: e.target.value })}
                                placeholder="Optional description"
                                rows={3}
                                className={cn(
                                    "w-full rounded-lg text-sm p-3 resize-none",
                                    isDark 
                                        ? "bg-white/4 border-white/8" 
                                        : "bg-white border-black/8"
                                )}
                            />
                        </div>
                        
                        <div className="flex gap-3 pt-4">
                            <button
                                onClick={() => {
                                    if (spaces.length > 0) {
                                        setShowCreateSpace(false)
                                    } else {
                                        onClose()
                                    }
                                }}
                                className={cn(
                                    "flex-1 px-4 py-2 rounded-lg text-sm font-medium",
                                    "bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600",
                                    "text-foreground transition-colors"
                                )}
                            >
                                {spaces.length > 0 ? 'Back' : 'Cancel'}
                            </button>
                            <button
                                onClick={handleCreateSpace}
                                disabled={isCreatingSpace || !newSpaceData.name.trim()}
                                className={cn(
                                    "flex-1 px-4 py-2 rounded-lg text-sm font-medium",
                                    "bg-primary hover:bg-primary/90 text-primary-foreground",
                                    "disabled:opacity-50 disabled:cursor-not-allowed",
                                    "transition-colors"
                                )}
                            >
                                {isCreatingSpace ? 'Creating...' : 'Create Space'}
                            </button>
                        </div>
                    </div>
                ) : (
                    // Form para atribuir a space existente
                    <div className="space-y-4">
                        <div>
                            <label className="text-sm font-medium text-foreground mb-2 block">
                                Select Space
                            </label>
                            <div className="flex gap-2 mb-2">
                                <select
                                    value={selectedSpaceId}
                                    onChange={(e) => setSelectedSpaceId(e.target.value)}
                                    className={cn(
                                        "flex-1 px-3 py-2 rounded-lg border",
                                        "bg-white dark:bg-gray-900",
                                        "border-gray-200 dark:border-gray-700",
                                        "text-foreground"
                                    )}
                                >
                                    <option value="">-- Select a space --</option>
                                    {spaces.map(space => (
                                        <option key={space.id} value={space.id}>
                                            {space.name}
                                        </option>
                                    ))}
                                </select>
                                <button
                                    onClick={() => setShowCreateSpace(true)}
                                    className={cn(
                                        "px-3 py-2 rounded-lg text-sm font-medium",
                                        "bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600",
                                        "text-foreground transition-colors flex items-center gap-1"
                                    )}
                                >
                                    <Plus className="w-4 h-4" />
                                    New
                                </button>
                            </div>
                        </div>
                        
                        <div>
                            <label className="text-sm font-medium text-foreground mb-2 block">
                                Access Level
                            </label>
                            <select
                                value={accessLevel}
                                onChange={(e) => {
                                    const level = e.target.value as 'full' | 'read-only' | 'custom'
                                    setAccessLevel(level)
                                    if (level !== 'custom') {
                                        setSelectedTables([])
                                    }
                                }}
                                className={cn(
                                    "w-full px-3 py-2 rounded-lg border",
                                    "bg-white dark:bg-gray-900",
                                    "border-gray-200 dark:border-gray-700",
                                    "text-foreground"
                                )}
                            >
                                <option value="full">Full Access</option>
                                <option value="read-only">Read Only</option>
                                <option value="custom">Custom (Select Tables)</option>
                            </select>
                        </div>
                        
                        {accessLevel === 'custom' && availableTables.length > 0 && (
                            <div>
                                <label className="text-sm font-medium text-foreground mb-2 block">
                                    Select Tables
                                </label>
                                <div className={cn(
                                    "max-h-48 overflow-y-auto border rounded-lg p-2",
                                    "bg-white dark:bg-gray-900",
                                    "border-gray-200 dark:border-gray-700"
                                )}>
                                    {availableTables.map(tableName => (
                                        <label
                                            key={tableName}
                                            className={cn(
                                                "flex items-center gap-2 p-2 rounded hover:bg-gray-100 dark:hover:bg-white/5",
                                                "cursor-pointer"
                                            )}
                                        >
                                            <input
                                                type="checkbox"
                                                checked={selectedTables.includes(tableName)}
                                                onChange={(e) => {
                                                    if (e.target.checked) {
                                                        setSelectedTables([...selectedTables, tableName])
                                                    } else {
                                                        setSelectedTables(selectedTables.filter(t => t !== tableName))
                                                    }
                                                }}
                                                className="rounded"
                                            />
                                            <span className="text-sm text-foreground">{tableName}</span>
                                        </label>
                                    ))}
                                </div>
                            </div>
                        )}
                        
                        <div className="flex gap-3 pt-4">
                            <button
                                onClick={onClose}
                                className={cn(
                                    "flex-1 px-4 py-2 rounded-lg text-sm font-medium",
                                    "bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600",
                                    "text-foreground transition-colors"
                                )}
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleAssign}
                                disabled={isSubmitting || !selectedSpaceId}
                                className={cn(
                                    "flex-1 px-4 py-2 rounded-lg text-sm font-medium",
                                    "bg-primary hover:bg-primary/90 text-primary-foreground",
                                    "disabled:opacity-50 disabled:cursor-not-allowed",
                                    "transition-colors"
                                )}
                            >
                                {isSubmitting ? 'Assigning...' : 'Assign & Finish'}
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </>
    )
}

// ============================================
// ADD PERMISSION MODAL COMPONENT
// ============================================
interface AddPermissionModalProps {
    isOpen: boolean
    onClose: () => void
    connectionId: string
    type: 'space' | 'crew'
    spaces: import("@/lib/api/spaces").Space[]
    crews: ApiCrew[]
    spaceCrews: Record<string, ApiCrew[]>
    connection: DataConnection | undefined
    onAdd: (connectionId: string, data: ConnectionPermissionCreate) => Promise<void>
    isDark: boolean
}

function AddPermissionModal({ 
    isOpen, 
    onClose, 
    connectionId, 
    type, 
    spaces, 
    crews, 
    spaceCrews,
    connection,
    onAdd,
    isDark 
}: AddPermissionModalProps) {
    const [selectedSpaceId, setSelectedSpaceId] = useState<string>('')
    const [selectedCrewId, setSelectedCrewId] = useState<string>('')
    const [accessLevel, setAccessLevel] = useState<'full' | 'read-only' | 'custom'>('full')
    const [selectedTables, setSelectedTables] = useState<string[]>([])
    const [isSubmitting, setIsSubmitting] = useState(false)
    
    const availableSpaces = spaces.filter(s => {
        // Filter out spaces that already have permission for this connection
        // This would need to check existing permissions, but for now show all
        return true
    })
    
    const availableCrews = type === 'crew' 
        ? crews.filter(c => {
            // Filter out crews that already have permission for this connection
            return true
        })
        : []
    
    const availableTables = connection?.metadata?.tables?.map(t => t.name) || []
    
    const handleSubmit = async () => {
        if (type === 'space' && !selectedSpaceId) {
            alert('Please select a space')
            return
        }
        if (type === 'crew' && !selectedCrewId) {
            alert('Please select a crew')
            return
        }
        if (accessLevel === 'custom' && selectedTables.length === 0) {
            alert('Please select at least one table for custom access')
            return
        }
        
        setIsSubmitting(true)
        try {
            await onAdd(connectionId, {
                space_id: type === 'space' && selectedSpaceId ? selectedSpaceId : undefined,
                crew_id: type === 'crew' && selectedCrewId ? selectedCrewId : undefined,
                access_level: accessLevel,
                table_access: accessLevel === 'custom' && selectedTables.length > 0 ? selectedTables : undefined
            })
            // Reset form
            setSelectedSpaceId('')
            setSelectedCrewId('')
            setAccessLevel('full')
            setSelectedTables([])
        } catch (error) {
            // Error already handled in onAdd
        } finally {
            setIsSubmitting(false)
        }
    }
    
    if (!isOpen) return null
    
    return (
        <>
            <div 
                className="fixed inset-0 z-50 bg-black/50" 
                onClick={onClose}
            />
            <div className={cn(
                "fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2",
                "w-full max-w-md rounded-lg border shadow-lg",
                "bg-white dark:bg-gray-800",
                "border-gray-200 dark:border-gray-700",
                "p-6"
            )}>
                <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold text-foreground">
                        Add {type === 'space' ? 'Space' : 'Crew'} Permission
                    </h3>
                    <button
                        onClick={onClose}
                        className={cn(
                            "p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-white/5",
                            "transition-colors"
                        )}
                    >
                        <X className="w-4 h-4" />
                    </button>
                </div>
                
                <div className="space-y-4">
                    {type === 'space' ? (
                        <div>
                            <label className="text-sm font-medium text-foreground mb-2 block">
                                Select Space
                            </label>
                            <select
                                value={selectedSpaceId}
                                onChange={(e) => setSelectedSpaceId(e.target.value)}
                                className={cn(
                                    "w-full px-3 py-2 rounded-lg border",
                                    "bg-white dark:bg-gray-900",
                                    "border-gray-200 dark:border-gray-700",
                                    "text-foreground"
                                )}
                            >
                                <option value="">-- Select a space --</option>
                                {availableSpaces.map(space => (
                                    <option key={space.id} value={space.id}>
                                        {space.name}
                                    </option>
                                ))}
                            </select>
                        </div>
                    ) : (
                        <div>
                            <label className="text-sm font-medium text-foreground mb-2 block">
                                Select Crew
                            </label>
                            <select
                                value={selectedCrewId}
                                onChange={(e) => setSelectedCrewId(e.target.value)}
                                className={cn(
                                    "w-full px-3 py-2 rounded-lg border",
                                    "bg-white dark:bg-gray-900",
                                    "border-gray-200 dark:border-gray-700",
                                    "text-foreground"
                                )}
                            >
                                <option value="">-- Select a crew --</option>
                                {availableCrews.map(crew => {
                                    // Find space that contains this crew
                                    const space = spaces.find(s => {
                                        const crewsInSpace = spaceCrews[s.id] || []
                                        return crewsInSpace.some(c => c.id === crew.id)
                                    })
                                    return (
                                        <option key={crew.id} value={crew.id}>
                                            {crew.name} {space ? `(${space.name})` : ''}
                                        </option>
                                    )
                                })}
                            </select>
                        </div>
                    )}
                    
                    <div>
                        <label className="text-sm font-medium text-foreground mb-2 block">
                            Access Level
                        </label>
                        <select
                            value={accessLevel}
                            onChange={(e) => {
                                const level = e.target.value as 'full' | 'read-only' | 'custom'
                                setAccessLevel(level)
                                if (level !== 'custom') {
                                    setSelectedTables([])
                                }
                            }}
                            className={cn(
                                "w-full px-3 py-2 rounded-lg border",
                                "bg-white dark:bg-gray-900",
                                "border-gray-200 dark:border-gray-700",
                                "text-foreground"
                            )}
                        >
                            <option value="full">Full Access</option>
                            <option value="read-only">Read Only</option>
                            <option value="custom">Custom (Select Tables)</option>
                        </select>
                    </div>
                    
                    {accessLevel === 'custom' && availableTables.length > 0 && (
                        <div>
                            <label className="text-sm font-medium text-foreground mb-2 block">
                                Select Tables
                            </label>
                            <div className={cn(
                                "max-h-48 overflow-y-auto border rounded-lg p-2",
                                "bg-white dark:bg-gray-900",
                                "border-gray-200 dark:border-gray-700"
                            )}>
                                {availableTables.map(tableName => (
                                    <label
                                        key={tableName}
                                        className={cn(
                                            "flex items-center gap-2 p-2 rounded hover:bg-gray-100 dark:hover:bg-white/5",
                                            "cursor-pointer"
                                        )}
                                    >
                                        <input
                                            type="checkbox"
                                            checked={selectedTables.includes(tableName)}
                                            onChange={(e) => {
                                                if (e.target.checked) {
                                                    setSelectedTables([...selectedTables, tableName])
                                                } else {
                                                    setSelectedTables(selectedTables.filter(t => t !== tableName))
                                                }
                                            }}
                                            className="rounded"
                                        />
                                        <span className="text-sm text-foreground">{tableName}</span>
                                    </label>
                                ))}
                            </div>
                        </div>
                    )}
                    
                    <div className="flex gap-3 pt-4">
                        <button
                            onClick={onClose}
                            className={cn(
                                "flex-1 px-4 py-2 rounded-lg text-sm font-medium",
                                "bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600",
                                "text-foreground transition-colors"
                            )}
                        >
                            Cancel
                        </button>
                        <button
                            onClick={handleSubmit}
                            disabled={isSubmitting || (type === 'space' && !selectedSpaceId) || (type === 'crew' && !selectedCrewId)}
                            className={cn(
                                "flex-1 px-4 py-2 rounded-lg text-sm font-medium",
                                "bg-primary hover:bg-primary/90 text-primary-foreground",
                                "disabled:opacity-50 disabled:cursor-not-allowed",
                                "transition-colors"
                            )}
                        >
                            {isSubmitting ? 'Adding...' : 'Add Permission'}
                        </button>
                    </div>
                </div>
            </div>
        </>
    )
}

// ============================================
// DELETE CONFIRMATION MODAL COMPONENT
// ============================================
interface DeleteConfirmationModalProps {
    isOpen: boolean
    onClose: () => void
    onConfirm: () => Promise<void>
    itemName: string
    itemType: 'connection' | 'space' | 'crew' | 'user'
    isDark: boolean
}

function DeleteConfirmationModal({ isOpen, onClose, onConfirm, itemName, itemType, isDark }: DeleteConfirmationModalProps) {
    const [confirmName, setConfirmName] = useState('')
    const [isDeleting, setIsDeleting] = useState(false)
    const isValid = confirmName === itemName
    
    useEffect(() => {
        if (!isOpen) {
            setConfirmName('')
            setIsDeleting(false)
        }
    }, [isOpen])
    
    if (!isOpen) return null
    
    const itemTypeLabel = {
        connection: 'connection',
        space: 'space',
        crew: 'crew',
        user: 'user'
    }[itemType]
    
    const handleConfirm = async () => {
        if (isValid && !isDeleting) {
            setIsDeleting(true)
            try {
                await onConfirm()
                // Não fechar aqui - deixar onConfirm controlar quando fechar
            } catch (error) {
                console.error('Error in delete confirmation:', error)
                setIsDeleting(false)
                // Não fechar modal em caso de erro
            }
        }
    }
    
    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
            <div 
                className="fixed inset-0 bg-black/20 backdrop-blur-sm" 
                onClick={onClose}
            />
            <div className={cn(
                "relative z-10 w-full max-w-md rounded-lg border shadow-xl",
                "bg-white dark:bg-gray-800",
                "border-gray-200 dark:border-gray-700",
                "p-6"
            )}>
                <h3 className="text-lg font-semibold text-foreground mb-2">
                    Delete {itemName}?
                </h3>
                <p className="text-sm text-muted-foreground mb-4">
                    This action cannot be undone. This will permanently delete the {itemTypeLabel} and all associated data.
                </p>
                <div className="mb-4">
                    <label className="text-sm font-medium text-foreground mb-2 block">
                        Type <span className="font-semibold">{itemName}</span> to confirm:
                    </label>
                    <Input
                        type="text"
                        value={confirmName}
                        onChange={(e) => setConfirmName(e.target.value)}
                        placeholder={itemName}
                        disabled={isDeleting}
                        className={cn(
                            "h-10 text-sm",
                            isDark 
                                ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                : "bg-white border-black/8 focus:border-black/15 focus:bg-white",
                            isDeleting && "opacity-50 cursor-not-allowed"
                        )}
                        autoFocus
                    />
                </div>
                <div className="flex items-center justify-end gap-3">
                    <button
                        onClick={onClose}
                        disabled={isDeleting}
                        className={cn(
                            "px-4 py-2 rounded-lg text-sm font-medium",
                            "hover:bg-gray-100 dark:hover:bg-gray-700",
                            "transition-colors",
                            isDeleting && "opacity-50 cursor-not-allowed"
                        )}
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handleConfirm}
                        disabled={!isValid || isDeleting}
                        className={cn(
                            "px-4 py-2 rounded-lg text-sm font-medium",
                            "bg-red-500 hover:bg-red-600 text-white",
                            "disabled:opacity-50 disabled:cursor-not-allowed",
                            "transition-colors flex items-center gap-2"
                        )}
                    >
                        {isDeleting && <RefreshCw className="w-4 h-4 animate-spin" />}
                        {isDeleting ? 'Deleting...' : 'Delete'}
                    </button>
                </div>
            </div>
        </div>
    )
}

// ============================================
// DATA CATALOG SECTION - Agnostic Connector System
// ============================================

// Export DatabasesSection as alias for backward compatibility
export function DatabasesSection({ isDark }: { isDark: boolean }) {
    return <DataCatalogSection isDark={isDark} />
}

export function DataCatalogSection({ isDark }: { isDark: boolean }) {
    // View mode state
    const [viewMode, setViewMode] = useState<'list' | 'detail' | 'permissions' | 'add' | 'tables'>('list')
    const [selectedConnectionForPermissions, setSelectedConnectionForPermissions] = useState<string | null>(null)
    const [selectedConnectionForTables, setSelectedConnectionForTables] = useState<string | null>(null)
    const [permissionsTab, setPermissionsTab] = useState<'spaces' | 'crew'>('spaces')
    const [addConnectionStep, setAddConnectionStep] = useState<1 | 2 | 3 | 4 | 5>(1)
    const [selectedConnectionType, setSelectedConnectionType] = useState<'database' | 'document' | 'api' | null>(null)
    const [selectedConnectorForAdd, setSelectedConnectorForAdd] = useState<ConnectorDefinition | null>(null)
    
    // API state
    const [connections, setConnections] = useState<DataConnection[]>([])
    const [isLoading, setIsLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const { connectors, fetchConnectors } = useConnectorsStore()
    
    // Load connectors on mount
    useEffect(() => {
        fetchConnectors().catch((err) => {
            // Don't break the app if connectors API fails - we have local registry as fallback
            console.warn('Failed to load connectors from API, using local registry:', err)
        })
    }, [fetchConnectors])
    
    // Load connections from backend
    useEffect(() => {
        const isMountedRef = { current: true }
        
        const loadConnections = async () => {
            setIsLoading(true)
            setError(null)
            try {
                const apiConnections = await connectionsApi.listConnections()
                
                if (!isMountedRef.current) return
                
                const formattedConnections: DataConnection[] = await Promise.all(
                    apiConnections.map(async (conn: Connection) => {
                        // Load metadata if available
                        let metadata: ConnectionMetadata | undefined
                        try {
                            const metadataResponse = await connectionsApi.getConnectionMetadata(conn.id)
                            metadata = {
                                tables: (metadataResponse.tables || []).map((t: any) => ({
                                    name: t.name,
                                    schema: t.schema || t.schema_name,
                                    rowCount: t.row_count,
                                    columns: (t.columns || []).map((col: any) => ({
                                        name: col.name,
                                        type: col.type,
                                        nullable: col.nullable,
                                        description: col.description
                                    }))
                                })),
                                schemas: (metadataResponse.schemas || []).map((s: any) => 
                                    typeof s === 'string' 
                                        ? { name: s, tables: [] }
                                        : { name: s.name || s, tables: s.tables || [] }
                                ),
                                lastMetadataUpdate: metadataResponse.last_metadata_update
            }
                        } catch (err) {
                            // Metadata loading failure is not critical, just log it
                            console.warn(`Failed to load metadata for connection ${conn.id}:`, err)
                        }
                        
                        // Validate and cast status to the correct type
                        const validStatus = (conn.status === 'active' || conn.status === 'inactive' || conn.status === 'error') 
                            ? conn.status 
                            : 'inactive' as 'active' | 'inactive' | 'error'
                        
                        return {
                            id: conn.id,
                            name: conn.name,
                            connectorId: conn.connector_id,
                            status: validStatus,
                            lastSync: conn.last_sync,
                            nextSync: conn.next_sync,
                            syncFrequency: conn.sync_frequency || '0 */6 * * *',
                            config: conn.config || {},
                            description: conn.description || '',
                            createdAt: conn.created_at || new Date().toISOString(),
                            updatedAt: conn.updated_at || new Date().toISOString(),
                            metadata
                        }
                    })
                )
                
                if (isMountedRef.current) {
                    setConnections(formattedConnections)
                }
            } catch (err) {
                console.error('Error loading connections:', err)
                if (isMountedRef.current) {
                    // Don't break the app - just show empty state
                    setConnections([])
                    const errorMessage = err instanceof Error ? err.message : 'Failed to load connections'
                    // Only show error if it's not a network/CORS error (backend might be down)
                    if (!errorMessage.toLowerCase().includes('fetch') && 
                        !errorMessage.toLowerCase().includes('network') &&
                        !errorMessage.toLowerCase().includes('cors')) {
                        setError(errorMessage)
                    }
                }
            } finally {
                if (isMountedRef.current) {
                    setIsLoading(false)
                }
            }
        }
        
        loadConnections()
        
        return () => {
            isMountedRef.current = false
        }
    }, [])
    
    const [selectedConnection, setSelectedConnection] = useState<string | null>(null)
    const [editingConnection, setEditingConnection] = useState<string | null>(null)
    const [selectedConnector, setSelectedConnector] = useState<ConnectorDefinition | null>(null)
    const [selectedAuthMethod, setSelectedAuthMethod] = useState<string>('')
    const [searchQuery, setSearchQuery] = useState('')
    const [filterCategory, setFilterCategory] = useState<string>('all')
    const [filterStatus, setFilterStatus] = useState<string>('all')
    const [filterSpace, setFilterSpace] = useState<string>('all')
    const [filterCrew, setFilterCrew] = useState<string>('all')
    const [testingConnection, setTestingConnection] = useState<string | null>(null)
    const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)
    const [tempConnectionId, setTempConnectionId] = useState<string | null>(null) // Para conexões temporárias criadas para teste
    const [syncingConnection, setSyncingConnection] = useState<string | null>(null) // Para controlar o sync de tabelas
    const [isCreatingNewConnection, setIsCreatingNewConnection] = useState(false) // Para controlar se estamos criando nova conexão
    const [showAssignSpaceModal, setShowAssignSpaceModal] = useState(false) // Modal para atribuir space
    const [expandedTable, setExpandedTable] = useState<string | null>(null) // Para controlar qual tabela está expandida
    const [connectionDashboardTab, setConnectionDashboardTab] = useState<'tables' | 'settings'>('tables') // Tab ativa no dashboard da conexão
    const [selectedTables, setSelectedTables] = useState<string[]>([]) // Tabelas selecionadas para atribuir ao space
    const [selectedSpaceId, setSelectedSpaceId] = useState<string>('') // Space selecionado para atribuir tabelas
    const [showCreateSpaceModal, setShowCreateSpaceModal] = useState(false) // Modal para criar novo space
    const [tableSearchQuery, setTableSearchQuery] = useState<string>('') // Busca de tabelas
    // Step 4 states - Assign tables to Spaces/Crews
    const [selectedTablesForAssignment, setSelectedTablesForAssignment] = useState<string[]>([]) // Tabelas selecionadas no Step 4
    const [selectedSpaceForAssignment, setSelectedSpaceForAssignment] = useState<string>('') // Space selecionado no Step 4
    const [selectedCrewForAssignment, setSelectedCrewForAssignment] = useState<string>('') // Crew selecionado no Step 4
    const [assignedTablesToSpaces, setAssignedTablesToSpaces] = useState<Record<string, { spaceId: string; tables: string[] }>>({}) // Tabelas atribuídas a Spaces
    const [assignedTablesToCrews, setAssignedTablesToCrews] = useState<Record<string, { crewId: string; tables: string[] }>>({}) // Tabelas atribuídas a Crews
    const [deleteModalOpen, setDeleteModalOpen] = useState(false)
    const [itemToDelete, setItemToDelete] = useState<{ id: string; name: string } | null>(null)
    const [currentPage, setCurrentPage] = useState(1)
    const [itemsPerPage, setItemsPerPage] = useState(10)
    
    
    // Permissions state - using real stores
    const { spaces, fetchSpaces, spaceCrews, fetchSpaceCrews } = useSpaceStore()
    const { crews, fetchCrews, crewMembers, fetchCrewMembers } = useCrewStore()
    const [permissions, setPermissions] = useState<ApiConnectionPermission[]>([])
    const [isLoadingPermissions, setIsLoadingPermissions] = useState(false)
    const [showAddPermissionModal, setShowAddPermissionModal] = useState(false)
    const [addPermissionType, setAddPermissionType] = useState<'space' | 'crew'>('space')
    
    // Load spaces and crews on mount
    useEffect(() => {
        fetchSpaces().catch(console.error)
        fetchCrews().catch(console.error)
    }, [fetchSpaces, fetchCrews])
    
    // Load crews for each space when spaces are loaded
    useEffect(() => {
        spaces.forEach(space => {
            if (!spaceCrews[space.id]) {
                fetchSpaceCrews(space.id).catch(console.error)
            }
        })
    }, [spaces, spaceCrews, fetchSpaceCrews])
    
    // Load members for each crew when crews are loaded
    useEffect(() => {
        crews.forEach(crew => {
            if (!crewMembers[crew.id]) {
                fetchCrewMembers(crew.id).catch(console.error)
            }
        })
    }, [crews, crewMembers, fetchCrewMembers])
    
    // Load permissions when viewing permissions for a connection
    useEffect(() => {
        if (selectedConnectionForPermissions) {
            loadPermissions(selectedConnectionForPermissions)
        }
    }, [selectedConnectionForPermissions])
    
    // Close delete modal when leaving dashboard (but only if modal is open)
    useEffect(() => {
        // Only close modal if we're leaving the detail view AND the modal is currently open
        // This prevents closing the modal immediately after opening it
        if (deleteModalOpen && (viewMode !== 'detail' || !editingConnection)) {
            setDeleteModalOpen(false)
            setItemToDelete(null)
        }
    }, [viewMode, editingConnection, deleteModalOpen])
    
    // Load permissions when editing a connection in dashboard (for permissions tab)
    useEffect(() => {
        if (editingConnection && viewMode === 'detail') {
            loadPermissions(editingConnection)
        }
    }, [editingConnection, viewMode])
    
    // Load form data when editing a connection in dashboard
    useEffect(() => {
        if (editingConnection && viewMode === 'detail') {
            const conn = connections.find(c => c.id === editingConnection)
            if (conn) {
                const connector = getConnectorById(conn.connectorId)
                if (connector) {
                    // Load form data from connection
                    const configData = { ...conn.config }
                    
                    // Try to determine auth method from config or use first one
                    let authMethod = connector.authMethods[0]?.type || ''
                    
                    // Check if auth method is stored in config
                    if (configData.auth_method) {
                        authMethod = configData.auth_method
                        // Remove auth_method from config to avoid showing it as a field
                        delete configData.auth_method
                    } else if (configData.authMethod) {
                        authMethod = configData.authMethod
                        delete configData.authMethod
                    }
                    
                    setFormData({
                        name: conn.name,
                        description: conn.description || '',
                        ...configData
                    })
                    setSelectedConnector(connector)
                    setSelectedAuthMethod(authMethod)
                }
            }
        }
    }, [editingConnection, viewMode, connections, connectionDashboardTab])
    
    // Reload form data when switching to Settings tab
    useEffect(() => {
        if (editingConnection && viewMode === 'detail' && connectionDashboardTab === 'settings') {
            const conn = connections.find(c => c.id === editingConnection)
            if (conn) {
                const connector = getConnectorById(conn.connectorId)
                if (connector) {
                    // Load form data from connection
                    const configData = { ...conn.config }
                    
                    // Try to determine auth method from config or use first one
                    let authMethod = connector.authMethods[0]?.type || ''
                    
                    // Check if auth method is stored in config
                    if (configData.auth_method) {
                        authMethod = configData.auth_method
                        delete configData.auth_method
                    } else if (configData.authMethod) {
                        authMethod = configData.authMethod
                        delete configData.authMethod
                    }
                    
                    setFormData({
                        name: conn.name,
                        description: conn.description || '',
                        ...configData
                    })
                    setSelectedConnector(connector)
                    setSelectedAuthMethod(authMethod)
                }
            }
        }
    }, [connectionDashboardTab, editingConnection, connections])
    
    const loadPermissions = async (connectionId: string) => {
        setIsLoadingPermissions(true)
        try {
            const perms = await permissionsApi.getConnectionPermissions(connectionId)
            setPermissions(perms)
        } catch (error) {
            console.error('Error loading permissions:', error)
            setPermissions([])
        } finally {
            setIsLoadingPermissions(false)
        }
    }
    
    // Form state for add/edit
    const [formData, setFormData] = useState<Record<string, any>>({
        name: '',
        description: '',
    })
    
    // Get connection permissions
    const getConnectionPermissions = (connectionId: string) => {
        return permissions.filter(p => p.connection_id === connectionId)
    }
    
    const getSpacePermissions = (spaceId: string) => {
        return permissions.filter(p => p.space_id === spaceId)
    }
    
    const getCrewPermissions = (crewId: string) => {
        return permissions.filter(p => p.crew_id === crewId)
    }
    
    const addPermission = async (connectionId: string, data: ConnectionPermissionCreate) => {
        try {
            const newPermission = await permissionsApi.createConnectionPermission(connectionId, data)
            setPermissions([...permissions, newPermission])
            setShowAddPermissionModal(false)
        } catch (error) {
            console.error('Error adding permission:', error)
            alert(`Error adding permission: ${error instanceof Error ? error.message : 'Unknown error'}`)
        }
    }
    
    const removePermission = async (permissionId: string) => {
        try {
            await permissionsApi.deletePermission(permissionId)
            setPermissions(permissions.filter(p => p.id !== permissionId))
        } catch (error) {
            console.error('Error removing permission:', error)
            alert(`Error removing permission: ${error instanceof Error ? error.message : 'Unknown error'}`)
        }
    }
    
    const updateTableAccess = async (permissionId: string, tables: string[]) => {
        try {
            const updated = await permissionsApi.updatePermission(permissionId, {
                access_level: 'custom',
                table_access: tables
            })
            setPermissions(permissions.map(p => p.id === permissionId ? updated : p))
        } catch (error) {
            console.error('Error updating table access:', error)
            alert(`Error updating table access: ${error instanceof Error ? error.message : 'Unknown error'}`)
        }
    }

    const filteredConnections = connections.filter(conn => {
        const connector = getConnectorById(conn.connectorId)
        const matchesSearch = conn.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
                            conn.description?.toLowerCase().includes(searchQuery.toLowerCase())
        const matchesCategory = filterCategory === 'all' || connector?.category === filterCategory
        const matchesStatus = filterStatus === 'all' || conn.status === filterStatus
        
        // Filter by space
        const connPermissions = getConnectionPermissions(conn.id)
        const connSpaces = connPermissions.filter(p => p.space_id).map(p => p.space_id!)
        const matchesSpace = filterSpace === 'all' || connSpaces.includes(filterSpace)
        
        // Filter by crew
        const connCrews = connPermissions.filter(p => p.crew_id).map(p => p.crew_id!)
        const matchesCrew = filterCrew === 'all' || connCrews.includes(filterCrew)
        
        return matchesSearch && matchesCategory && matchesStatus && matchesSpace && matchesCrew
    })
    
    const paginatedConnections = filteredConnections.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage)
    const totalPages = Math.ceil(filteredConnections.length / itemsPerPage)
    
    const stats = {
        total: connections.length,
        active: connections.filter(c => c.status === 'active').length,
        inactive: connections.filter(c => c.status === 'inactive').length,
    }

    // Helper function to get connector (backend first, then local registry)
    const getConnector = (connectorId: string): ConnectorDefinition | undefined => {
        const backendConnector = connectors.find(c => c.id === connectorId)
        if (backendConnector) {
            const localConnector = getConnectorById(connectorId)
            return localConnector || {
                id: backendConnector.id,
                name: backendConnector.name,
                category: backendConnector.category as any,
                description: backendConnector.description,
                icon: iconMap[backendConnector.icon || 'database'] || iconMap.database,
                fields: backendConnector.fields || [],
                authMethods: backendConnector.auth_methods || [],
                configSchema: backendConnector.config_schema,
                syncFrequency: backendConnector.sync_frequency
            }
        }
        return getConnectorById(connectorId)
    }

    // No pagination for now - show all filtered connections
    const uniqueCategories = Array.from(new Set(connections.map(c => {
        const connector = getConnector(c.connectorId)
        return connector?.category || 'unknown'
    })))

    const deleteConnection = async (id: string) => {
        console.log('[deleteConnection] Function called with ID:', id)
        console.log('[deleteConnection] Endpoint: DELETE http://localhost:8000/api/v1/connections/' + id)
        try {
            console.log('[deleteConnection] Calling connectionsApi.deleteConnection...')
            // Chamar a API para deletar no backend
            await connectionsApi.deleteConnection(id)
            console.log('[deleteConnection] API call successful, updating UI...')
            
            // Atualizar o estado local removendo a conexão deletada
            setConnections(prevConnections => prevConnections.filter(c => c.id !== id))
            
            // Limpar seleções se a conexão deletada estava selecionada
            if (selectedConnection === id) {
                setSelectedConnection(null)
            }
            
            // Se estávamos editando a conexão deletada, voltar para a lista
            if (editingConnection === id) {
                setEditingConnection(null)
                setViewMode('list')
            }
            
            // Fechar modal apenas em caso de sucesso
            setDeleteModalOpen(false)
            setItemToDelete(null)
            
            // Limpar qualquer erro anterior
            setError(null)
            console.log('[deleteConnection] Deletion completed successfully')
        } catch (err) {
            console.error('[deleteConnection] Error deleting connection:', err)
            const errorMessage = err instanceof Error ? err.message : 'Failed to delete connection'
            setError(errorMessage)
            // NÃO fechar o modal em caso de erro - deixar usuário tentar novamente
            alert(`Error deleting connection: ${errorMessage}`)
            // Re-lançar o erro para que o modal saiba que falhou
            throw err
        }
    }


    
    const handleEditConnection = (connId: string) => {
        const conn = connections.find(c => c.id === connId)
        if (!conn) return
        
        setEditingConnection(connId)
        setViewMode('detail')
        setConnectionDashboardTab('tables')
    }
    
    // Function to validate if all required fields are filled
    const isFormValid = (): boolean => {
        const connector = selectedConnector || selectedConnectorForAdd
        if (!connector) return false
        
        // Check connection name
        if (!formData.name || formData.name.trim() === '') return false
        
        // Check all required connection fields
        const requiredFields = connector.fields.filter(f => f.required)
        for (const field of requiredFields) {
            const value = formData[field.key]
            if (value === undefined || value === null || value === '' || (typeof value === 'string' && value.trim() === '')) {
                return false
            }
        }
        
        // Check all required auth method fields
        const currentAuthMethod = connector.authMethods.find(m => m.type === selectedAuthMethod)
        if (currentAuthMethod) {
            const requiredAuthFields = currentAuthMethod.fields.filter(f => f.required)
            for (const field of requiredAuthFields) {
                const value = formData[field.key]
                if (value === undefined || value === null || value === '' || (typeof value === 'string' && value.trim() === '')) {
                    return false
                }
            }
        }
        
        return true
    }
    
    const handleTestConnection = async () => {
        const connector = selectedConnector || selectedConnectorForAdd
        if (!connector) return
        
        // If editing existing connection, test it
        if (editingConnection) {
            setTestingConnection(editingConnection)
            setTestResult(null)
            try {
                const result = await connectionsApi.testConnection(editingConnection)
                setTestResult({
                    success: result.success,
                    message: result.message || (result.success 
                        ? 'Connection successful! All credentials are valid.'
                        : 'Connection failed. Please check your credentials and try again.')
                })
            } catch (err) {
                setTestResult({
                    success: false,
                    message: err instanceof Error ? err.message : 'Failed to test connection'
                })
            } finally {
                setTestingConnection(null)
            }
        } else {
            // For new connections, create a temporary connection, test it, and keep it if successful
            setTestingConnection('temp')
            setTestResult(null)
            
            try {
                // Delete temp connection if it exists
                if (tempConnectionId) {
                    try {
                        await connectionsApi.deleteConnection(tempConnectionId)
                    } catch (err) {
                        // Ignore errors when deleting temp connection
                        console.warn('Failed to delete temp connection:', err)
                    }
                    setTempConnectionId(null)
                }
                
                // Create temporary connection
                const tempConn = await connectionsApi.createConnection({
                    name: `temp-${Date.now()}`,
                    connector_id: connector.id,
                    description: 'Temporary connection for testing',
                    config: { ...formData }
                })
                
                setTempConnectionId(tempConn.id)
                
                // Test the connection
                const result = await connectionsApi.testConnection(tempConn.id)
                setTestResult({
                    success: result.success,
                    message: result.message || (result.success 
                        ? 'Connection successful! All credentials are valid. You can now create the connection.'
                        : 'Connection failed. Please check your credentials and try again.')
                })
                
                // If test failed, delete temp connection
                if (!result.success && tempConn.id) {
                    try {
                        await connectionsApi.deleteConnection(tempConn.id)
                        setTempConnectionId(null)
                    } catch (err) {
                        console.warn('Failed to delete temp connection after failed test:', err)
                    }
                }
            } catch (err) {
                setTestResult({
                    success: false,
                    message: err instanceof Error ? err.message : 'Failed to test connection'
                })
                // Clean up temp connection on error
                if (tempConnectionId) {
                    try {
                        await connectionsApi.deleteConnection(tempConnectionId)
                        setTempConnectionId(null)
                    } catch (deleteErr) {
                        console.warn('Failed to delete temp connection on error:', deleteErr)
                    }
                }
            } finally {
                setTestingConnection(null)
            }
        }
    }
    
    const handleSaveConnection = async () => {
        const connector = selectedConnector || selectedConnectorForAdd
        if (!connector) return
        
        setIsLoading(true)
        setError(null)
        
        try {
        if (editingConnection) {
            // Update existing connection
            // Prepare config data, ensuring auth_method is included
            const configToSave = { ...formData }
            if (selectedAuthMethod) {
                configToSave.auth_method = selectedAuthMethod
            }
            
                const updated = await connectionsApi.updateConnection(editingConnection, {
                    name: formData.name,
                    description: formData.description || '',
                    config: configToSave
                })
                
            // Update connections list with new data
            setConnections(prevConnections => prevConnections.map(c => 
                c.id === editingConnection
                    ? {
                        ...c,
                            name: updated.name,
                            description: updated.description || '',
                            config: updated.config || {},
                            updatedAt: updated.updated_at || new Date().toISOString()
                    }
                    : c
            ))
            
            // Update form data with saved values to reflect changes
            const updatedConfig = { ...updated.config }
            let authMethod = selectedAuthMethod
            
            // Extract auth_method from config if present
            if (updatedConfig.auth_method) {
                authMethod = updatedConfig.auth_method
                delete updatedConfig.auth_method
            } else if (updatedConfig.authMethod) {
                authMethod = updatedConfig.authMethod
                delete updatedConfig.authMethod
            }
            
            setFormData({
                name: updated.name,
                description: updated.description || '',
                ...updatedConfig
            })
            setSelectedAuthMethod(authMethod)
            
            // Don't reset viewMode - stay in dashboard
            // Show success feedback (could add a toast notification here)
        } else {
            // Create new - use temp connection if it exists and test was successful
            let newConn: Connection
            // Prepare config data, ensuring auth_method is included
            const configToSave = { ...formData }
            if (selectedAuthMethod) {
                configToSave.auth_method = selectedAuthMethod
            }
            
            if (tempConnectionId && testResult?.success) {
                // Update the temp connection with the final name and description
                newConn = await connectionsApi.updateConnection(tempConnectionId, {
                    name: formData.name,
                    description: formData.description || '',
                    config: configToSave
                })
            } else {
                // Create new connection
                newConn = await connectionsApi.createConnection({
                    name: formData.name,
                    connector_id: connector.id,
                    description: formData.description || '',
                    config: configToSave
                })
            }
            
            const newConnection: DataConnection = {
                id: newConn.id,
                name: newConn.name,
                connectorId: newConn.connector_id,
                status: ((newConn.status === 'active' || newConn.status === 'inactive' || newConn.status === 'error') 
                    ? newConn.status 
                    : 'active') as 'active' | 'inactive' | 'error',
                lastSync: newConn.last_sync,
                nextSync: newConn.next_sync,
                syncFrequency: connector.syncFrequency?.default || '0 */6 * * *',
                config: newConn.config || {},
                description: newConn.description || '',
                createdAt: newConn.created_at || new Date().toISOString(),
                updatedAt: newConn.updated_at || new Date().toISOString(),
            }
            setConnections(prevConnections => [...prevConnections, newConnection])
            
            // Reset temp connection ID since we've converted it to a real connection
            setTempConnectionId(null)
            
            // Reset for new connection flow
            setViewMode('list')
            setEditingConnection(null)
            setSelectedConnector(null)
            setSelectedConnectorForAdd(null)
            setSelectedAuthMethod('')
            setAddConnectionStep(1)
            setSelectedConnectionType(null)
            setFormData({ name: '', description: '' })
            setTestResult(null)
        }
        } catch (err) {
            console.error('Error saving connection:', err)
            setError(err instanceof Error ? err.message : 'Failed to save connection')
        } finally {
            setIsLoading(false)
        }
    }
    
    const handleCancelEdit = () => {
        setViewMode('list')
        setEditingConnection(null)
        setSelectedConnector(null)
        setSelectedAuthMethod('')
        setFormData({ name: '', description: '' })
        setTestResult(null)
    }

    const handleSyncNow = async (connectionId: string) => {
        try {
            setError(null) // Limpar erro anterior
            
            const result = await connectionsApi.syncConnection(connectionId)
            
            if (!result.success) {
                throw new Error(result.message || 'Failed to sync connection')
            }
            
            // Reload connection to get updated metadata
            const updated = await connectionsApi.getConnection(connectionId)
            
            // Usar função de atualização funcional para evitar estado stale
            setConnections(prevConnections => prevConnections.map(c => 
                c.id === connectionId 
                    ? { 
                        ...c, 
                        lastSync: updated.last_sync || new Date().toISOString(),
                        nextSync: updated.next_sync,
                        status: ((updated.status === 'active' || updated.status === 'inactive' || updated.status === 'error') 
                            ? updated.status 
                            : 'active') as 'active' | 'inactive' | 'error'
                    }
                    : c
            ))
            
            // Reload metadata
            try {
                const metadataResponse = await connectionsApi.getConnectionMetadata(connectionId)
                setConnections(prevConnections => prevConnections.map(c => 
                    c.id === connectionId 
                        ? {
                            ...c,
                            metadata: {
                                tables: (metadataResponse.tables || []).map((t: any) => ({
                                    name: t.name,
                                    schema: t.schema || t.schema_name,
                                    rowCount: t.row_count,
                                    columns: (t.columns || []).map((col: any) => ({
                                        name: col.name,
                                        type: col.type,
                                        nullable: col.nullable,
                                        description: col.description
                                    }))
                                })),
                                schemas: (metadataResponse.schemas || []).map((s: any) => 
                                    typeof s === 'string' 
                                        ? { name: s, tables: [] }
                                        : { name: s.name || s, tables: s.tables || [] }
                                ),
                                lastMetadataUpdate: metadataResponse.last_metadata_update
                            }
                        }
                        : c
                ))
            } catch (err) {
                console.warn('Failed to reload metadata:', err)
            }
        } catch (err) {
            console.error('Error syncing connection:', err)
            const errorMessage = err instanceof Error ? err.message : 'Failed to sync connection'
            setError(errorMessage)
            // Mostrar alerta também para feedback imediato
            alert(`Error syncing connection: ${errorMessage}`)
        }
    }

    const handleSyncTables = async (connectionId: string) => {
        setSyncingConnection(connectionId)
        setError(null)
        
        try {
            // Call sync to discover tables
            const result = await connectionsApi.syncConnection(connectionId)
            
            if (!result.success) {
                throw new Error(result.message || 'Failed to sync tables')
            }
            
            // Reload connection to get updated metadata
            const updated = await connectionsApi.getConnection(connectionId)
            
            // Reload metadata
            const metadataResponse = await connectionsApi.getConnectionMetadata(connectionId)
            
            // Format metadata
            const formattedMetadata: ConnectionMetadata = {
                tables: (metadataResponse.tables || []).map((t: any) => ({
                    name: t.name,
                    schema: t.schema || t.schema_name,
                    rowCount: t.row_count,
                    columns: (t.columns || []).map((col: any) => ({
                        name: col.name,
                        type: col.type,
                        nullable: col.nullable,
                        description: col.description
                    }))
                })),
                schemas: (metadataResponse.schemas || []).map((s: any) => 
                    typeof s === 'string' 
                        ? { name: s, tables: [] }
                        : { name: s.name || s, tables: s.tables || [] }
                ),
                lastMetadataUpdate: metadataResponse.last_metadata_update
            }
            
            // Check if connection exists in the list
            const existingConnection = connections.find(c => c.id === connectionId)
            
            let updatedConnections: DataConnection[]
            
            if (existingConnection) {
                // Update existing connection
                updatedConnections = connections.map(c => 
                    c.id === connectionId 
                        ? {
                            ...c,
                            lastSync: updated.last_sync || new Date().toISOString(),
                            nextSync: updated.next_sync,
                            status: ((updated.status === 'active' || updated.status === 'inactive' || updated.status === 'error') 
                            ? updated.status 
                            : 'active') as 'active' | 'inactive' | 'error',
                            metadata: formattedMetadata
                        }
                        : c
                )
            } else {
                // Add new connection (for temp connections)
                const connector = connectors.find(c => c.id === updated.connector_id) || 
                                 getConnectorById(updated.connector_id)
                
                const newConnection: DataConnection = {
                    id: updated.id,
                    name: updated.name,
                    connectorId: updated.connector_id,
                    status: ((updated.status === 'active' || updated.status === 'inactive' || updated.status === 'error') 
                        ? updated.status 
                        : 'active') as 'active' | 'inactive' | 'error',
                    lastSync: updated.last_sync || new Date().toISOString(),
                    nextSync: updated.next_sync,
                    syncFrequency: updated.sync_frequency || '0 */6 * * *',
                    config: updated.config || {},
                    description: updated.description || '',
                    createdAt: updated.created_at || new Date().toISOString(),
                    updatedAt: updated.updated_at || new Date().toISOString(),
                    metadata: formattedMetadata
                }
                
                updatedConnections = [...connections, newConnection]
            }
            
            // Update state
            setConnections(updatedConnections)
            
            // Se for uma conexão temporária no fluxo de Add Connection, ir para Step 4
            if (tempConnectionId === connectionId && viewMode === 'add') {
                // Reset assignment states
                setSelectedTablesForAssignment([])
                setSelectedSpaceForAssignment('')
                setSelectedCrewForAssignment('')
                setTableSearchQuery('')
                setAddConnectionStep(4)
            } else {
                // Se for uma conexão existente, navegar para tables view
            setSelectedConnectionForTables(connectionId)
            setViewMode('tables')
            }
        } catch (err) {
            console.error('Error syncing tables:', err)
            setError(err instanceof Error ? err.message : 'Failed to sync tables')
        } finally {
            setSyncingConnection(null)
        }
    }

    // Handler para criar space
    const handleCreateSpace = async (spaceData: { name: string; description: string; color: string }) => {
        const { createSpace } = useSpaceStore.getState()
        // Note: Space API doesn't support color field, so we remove it
        const newSpace = await createSpace({
            name: spaceData.name,
            description: spaceData.description
        })
        // Recarregar lista de spaces
        await fetchSpaces()
        return newSpace
    }

    // Handler para atribuir conexão a space
    const handleAssignToSpace = async (connectionId: string, spaceId: string, accessLevel: string, selectedTables?: string[]) => {
        await permissionsApi.createConnectionPermission(connectionId, {
            space_id: spaceId,
            access_level: accessLevel as any,
            table_access: accessLevel === 'custom' && selectedTables && selectedTables.length > 0 ? selectedTables : undefined
        })
    }

    // Handler para finalizar conexão
    const handleFinishConnection = async () => {
        if (tempConnectionId) {
            try {
                // Prepare config data, ensuring auth_method is included
                const configToSave = { ...formData }
                if (selectedAuthMethod) {
                    configToSave.auth_method = selectedAuthMethod
                }
                
                // Atualizar conexão temporária com nome final
                const updated = await connectionsApi.updateConnection(tempConnectionId, {
                    name: formData.name,
                    description: formData.description || '',
                    config: configToSave
                })
                
                // Atualizar na lista
                setConnections(connections.map(c => 
                    c.id === tempConnectionId 
                        ? { ...c, name: updated.name, description: updated.description || '' }
                        : c
                ))
                
                // Reset tudo
                setTempConnectionId(null)
                setIsCreatingNewConnection(false)
                setViewMode('list')
                setSelectedConnectionForTables(null)
                setFormData({ name: '', description: '' })
                setAddConnectionStep(1)
                setSelectedConnectionType(null)
                setSelectedConnectorForAdd(null)
                setSelectedAuthMethod('')
                setTestResult(null)
                // Reset Step 4 states
                setSelectedTablesForAssignment([])
                setSelectedSpaceForAssignment('')
                setSelectedCrewForAssignment('')
                setAssignedTablesToSpaces({})
                setAssignedTablesToCrews({})
                setTableSearchQuery('')
                setTestResult(null)
                setAddConnectionStep(1)
                setSelectedConnectionType(null)
                setSelectedConnectorForAdd(null)
                setShowAssignSpaceModal(false)
            } catch (err) {
                console.error('Error finalizing connection:', err)
                setError(err instanceof Error ? err.message : 'Failed to finalize connection')
            }
        }
    }

    // Render permissions view
    if (viewMode === 'permissions' && selectedConnectionForPermissions) {
        const conn = connections.find(c => c.id === selectedConnectionForPermissions)
        if (!conn) {
            setViewMode('list')
            setSelectedConnectionForPermissions(null)
            return null
        }
        const connPermissions = getConnectionPermissions(conn.id)
        const spacePerms = connPermissions.filter(p => p.space_id)
        const crewPerms = connPermissions.filter(p => p.crew_id)
        
        return (
            <div className="h-full flex flex-col">
                {/* Header with Back Button */}
                <div className={cn(
                    "px-5 py-4 border-b",
                    isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
                )}>
                    <div className="flex items-center gap-3 mb-4">
                        <button
                            onClick={() => {
                                setViewMode('list')
                                setSelectedConnectionForPermissions(null)
                            }}
                            className={cn(
                                "p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-white/5 transition-colors"
                            )}
                        >
                            <ChevronLeft className="w-4 h-4" />
                        </button>
                        <div className="flex-1">
                            <h2 className="text-lg font-semibold text-foreground">
                                {conn.name} - Permissions
                            </h2>
                            <p className="text-xs text-muted-foreground">
                                Manage access to this connection for spaces and crews
                            </p>
                        </div>
                    </div>
                    
                    {/* Tabs */}
                    <div className="flex gap-2 border-b border-gray-200 dark:border-gray-700">
                        <button
                            onClick={() => setPermissionsTab('spaces')}
                            className={cn(
                                "px-4 py-2 text-sm font-medium border-b-2 transition-colors",
                                permissionsTab === 'spaces'
                                    ? "border-blue-500 text-blue-600 dark:text-blue-400"
                                    : "border-transparent text-muted-foreground hover:text-foreground"
                            )}
                        >
                            Spaces ({spacePerms.length})
                        </button>
                        <button
                            onClick={() => setPermissionsTab('crew')}
                            className={cn(
                                "px-4 py-2 text-sm font-medium border-b-2 transition-colors",
                                permissionsTab === 'crew'
                                    ? "border-blue-500 text-blue-600 dark:text-blue-400"
                                    : "border-transparent text-muted-foreground hover:text-foreground"
                            )}
                        >
                            Crew ({crewPerms.length})
                        </button>
                    </div>
                </div>
                
                {/* Content */}
                <div className="flex-1 overflow-y-auto p-5">
                    {permissionsTab === 'spaces' ? (
                        <div className="space-y-4">
                            {spacePerms.length === 0 ? (
                                <div className="flex flex-col items-center justify-center py-12">
                                    <Shield className="w-12 h-12 text-muted-foreground mb-4" />
                                    <p className="text-sm text-muted-foreground mb-4">No space permissions assigned</p>
                                    <button
                                        onClick={() => {
                                            setAddPermissionType('space')
                                            setShowAddPermissionModal(true)
                                        }}
                                        className={cn(
                                            "px-4 py-2 rounded-lg text-sm font-medium",
                                            "bg-primary hover:bg-primary/90 text-primary-foreground",
                                            "transition-colors"
                                        )}
                                    >
                                        Add Space Access
                                    </button>
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    {spacePerms.map(perm => {
                                        const space = spaces.find(s => s.id === perm.space_id)
                                        if (!space) return null
                                        const spaceCrewsList = spaceCrews[space.id] || []
                                        const totalMembers = spaceCrewsList.reduce((sum, crew) => {
                                            const members = crewMembers[crew.id] || []
                                            return sum + members.length
                                        }, 0)
                                        
                                        return (
                                            <div
                                                key={perm.id}
                                                className={cn(
                                                    "p-4 rounded-lg border",
                                                    "bg-white dark:bg-gray-800",
                                                    "border-gray-200 dark:border-gray-700"
                                                )}
                                            >
                                                <div className="flex items-center justify-between mb-3">
                                                    <div>
                                                        <h3 className="text-sm font-semibold text-foreground">{space.name}</h3>
                                                        <p className="text-xs text-muted-foreground mt-1">Access Level: {perm.access_level}</p>
                                                    </div>
                                                    <button
                                                        onClick={() => removePermission(perm.id)}
                                                        className={cn(
                                                            "px-3 py-1.5 rounded text-xs font-medium",
                                                            "hover:bg-red-50 dark:hover:bg-red-900/20 text-red-500",
                                                            "transition-colors"
                                                        )}
                                                    >
                                                        Remove
                                                    </button>
                                                </div>
                                                <div className="grid grid-cols-3 gap-4 mt-3 pt-3 border-t border-gray-200 dark:border-gray-700">
                                                    <div>
                                                        <p className="text-xs text-muted-foreground mb-1">Crews</p>
                                                        <p className="text-sm font-semibold text-foreground">{spaceCrewsList.length}</p>
                                                    </div>
                                                    <div>
                                                        <p className="text-xs text-muted-foreground mb-1">Members</p>
                                                        <p className="text-sm font-semibold text-foreground">{totalMembers}</p>
                                                    </div>
                                                    <div>
                                                        <p className="text-xs text-muted-foreground mb-1">Tables</p>
                                                        <p className="text-sm font-semibold text-foreground">
                                                            {conn.metadata?.tables?.length || 0}
                                                        </p>
                                                    </div>
                                                </div>
                                            </div>
                                        )
                                    })}
                                </div>
                            )}
                        </div>
                    ) : (
                        <div className="space-y-4">
                            {crewPerms.length === 0 ? (
                                <div className="flex flex-col items-center justify-center py-12">
                                    <Shield className="w-12 h-12 text-muted-foreground mb-4" />
                                    <p className="text-sm text-muted-foreground mb-4">No crew permissions assigned</p>
                                    <button
                                        onClick={() => {
                                            setAddPermissionType('crew')
                                            setShowAddPermissionModal(true)
                                        }}
                                        className={cn(
                                            "px-4 py-2 rounded-lg text-sm font-medium",
                                            "bg-primary hover:bg-primary/90 text-primary-foreground",
                                            "transition-colors"
                                        )}
                                    >
                                        Add Crew Access
                                    </button>
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    {crewPerms.map(perm => {
                                        const crew = crews.find(c => c.id === perm.crew_id)
                                        if (!crew) return null
                                        const space = spaces.find(s => {
                                            // Find space that contains this crew
                                            const crewsInSpace = spaceCrews[s.id] || []
                                            return crewsInSpace.some(c => c.id === crew.id)
                                        })
                                        
                                        return (
                                            <div
                                                key={perm.id}
                                                className={cn(
                                                    "p-4 rounded-lg border",
                                                    "bg-white dark:bg-gray-800",
                                                    "border-gray-200 dark:border-gray-700"
                                                )}
                                            >
                                                <div className="flex items-center justify-between mb-3">
                                                    <div>
                                                        <h3 className="text-sm font-semibold text-foreground">{crew.name}</h3>
                                                        <p className="text-xs text-muted-foreground mt-1">
                                                            {space?.name} • Access Level: {perm.access_level}
                                                        </p>
                                                    </div>
                                                    <button
                                                        onClick={() => removePermission(perm.id)}
                                                        className={cn(
                                                            "px-3 py-1.5 rounded text-xs font-medium",
                                                            "hover:bg-red-50 dark:hover:bg-red-900/20 text-red-500",
                                                            "transition-colors"
                                                        )}
                                                    >
                                                        Remove
                                                    </button>
                                                </div>
                                                <div className="grid grid-cols-3 gap-4 mt-3 pt-3 border-t border-gray-200 dark:border-gray-700">
                                                    <div>
                                                        <p className="text-xs text-muted-foreground mb-1">Members</p>
                                                        <p className="text-sm font-semibold text-foreground">{(crewMembers[crew.id] || []).length}</p>
                                                    </div>
                                                    <div>
                                                        <p className="text-xs text-muted-foreground mb-1">Tables Access</p>
                                                        <p className="text-sm font-semibold text-foreground">
                                                            {perm.table_access?.length || 0} / {conn.metadata?.tables?.length || 0}
                                                        </p>
                                                    </div>
                                                    <div>
                                                        <p className="text-xs text-muted-foreground mb-1">Last Updated</p>
                                                        <p className="text-sm font-semibold text-foreground">
                                                            {perm.updated_at ? new Date(perm.updated_at).toLocaleDateString() : 'N/A'}
                                                        </p>
                                                    </div>
                                                </div>
                                                {perm.table_access && perm.table_access.length > 0 && (
                                                    <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-700">
                                                        <p className="text-xs text-muted-foreground mb-2">Accessible Tables:</p>
                                                        <div className="flex flex-wrap gap-1.5">
                                                            {perm.table_access.map(tableName => (
                                                                <span
                                                                    key={tableName}
                                                                    className={cn(
                                                                        "text-[10px] px-2 py-1 rounded",
                                                                        "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                                                                    )}
                                                                >
                                                                    {tableName}
                                                                </span>
                                                            ))}
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        )
                                    })}
                                </div>
                            )}
                        </div>
                    )}
                </div>
                
                {/* Add Permission Modal */}
                {showAddPermissionModal && selectedConnectionForPermissions && (
                    <AddPermissionModal
                        isOpen={showAddPermissionModal}
                        onClose={() => setShowAddPermissionModal(false)}
                        connectionId={selectedConnectionForPermissions}
                        type={addPermissionType}
                        spaces={spaces}
                        crews={crews}
                        spaceCrews={spaceCrews}
                        connection={connections.find(c => c.id === selectedConnectionForPermissions)}
                        onAdd={addPermission}
                        isDark={isDark}
                    />
                )}
            </div>
        )
    }

    // Render tables view
    if (viewMode === 'tables' && selectedConnectionForTables) {
        const conn = connections.find(c => c.id === selectedConnectionForTables)
        if (!conn) {
            setViewMode('list')
            setSelectedConnectionForTables(null)
            return null
        }

        const tables = conn.metadata?.tables || []
        const connPermissions = getConnectionPermissions(conn.id)
        const spacePerms = connPermissions.filter(p => p.space_id)

        // Se está criando nova conexão, usar layout de 2 colunas igual ao dashboard
        if (isCreatingNewConnection) {
            return (
                <div className="h-full flex flex-col">
                    {/* Header */}
                    <div className={cn(
                        "px-5 py-4 border-b flex-shrink-0",
                        isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
                    )}>
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-3">
                                <button
                                    onClick={() => {
                                        setViewMode('list')
                                        setSelectedConnectionForTables(null)
                                        setIsCreatingNewConnection(false)
                                        setSelectedTables([])
                                        setSelectedSpaceId('')
                                    }}
                                    className={cn(
                                        "p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-white/5 transition-colors"
                                    )}
                                >
                                    <ChevronLeft className="w-4 h-4" />
                                </button>
                                <div>
                                    <h2 className="text-lg font-semibold text-foreground">{conn.name}</h2>
                                    <p className="text-xs text-muted-foreground">
                                        {tables.length} tables discovered
                                    </p>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Content - 2 Colunas */}
                    <div className="flex-1 flex overflow-hidden">
                        {/* Coluna Esquerda - Todas as Tabelas */}
                        <div className="flex-1 border-r border-gray-200 dark:border-gray-700 overflow-y-auto p-5">
                            <div className="mb-4">
                                <h3 className="text-sm font-semibold text-foreground mb-2">
                                    Available Tables ({tables.length})
                                </h3>
                                <p className="text-xs text-muted-foreground mb-3">
                                    Select tables to assign to a space
                                </p>
                                
                                {/* Search Bar */}
                                <div className="relative">
                                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                                    <Input
                                        type="text"
                                        placeholder="Search tables..."
                                        value={tableSearchQuery}
                                        onChange={(e) => setTableSearchQuery(e.target.value)}
                                        className={cn(
                                            "pl-9 h-9 text-sm",
                                            isDark 
                                                ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                                : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                                        )}
                                    />
                                </div>
                            </div>
                            
                            {(() => {
                                // Filtrar tabelas baseado na busca
                                const filteredTables = tables.filter(table => {
                                    if (!tableSearchQuery.trim()) return true
                                    const query = tableSearchQuery.toLowerCase()
                                    return table.name.toLowerCase().includes(query) || 
                                           (table.schema || 'public').toLowerCase().includes(query)
                                })
                                
                                return filteredTables.length === 0 ? (
                                    <div className="text-sm text-muted-foreground text-center py-12">
                                        {tableSearchQuery ? `No tables found matching "${tableSearchQuery}"` : 'No tables available for this connection.'}
                                    </div>
                                ) : (
                                    <div className="space-y-2">
                                        {filteredTables.map((table) => {
                                        const tableKey = `${table.schema || 'public'}.${table.name}`
                                        const isSelected = selectedTables.includes(tableKey)
                                        
                                        // Encontrar quais spaces já têm esta tabela (se houver)
                                        const spacesWithThisTable = spacePerms
                                            .filter(perm => perm.table_access?.includes(table.name))
                                            .map(perm => spaces.find(s => s.id === perm.space_id))
                                            .filter((s): s is Space => s !== undefined)
                                        
                                        return (
                                            <div
                                                key={tableKey}
                                                className={cn(
                                                    "p-3 rounded-lg border cursor-pointer transition-all",
                                                    "bg-white dark:bg-gray-800",
                                                    "border-gray-200 dark:border-gray-700",
                                                    isSelected 
                                                        ? "border-blue-500 bg-blue-50 dark:bg-blue-900/20" 
                                                        : "hover:border-blue-300 dark:hover:border-blue-600"
                                                )}
                                                onClick={() => {
                                                    if (isSelected) {
                                                        setSelectedTables(selectedTables.filter(t => t !== tableKey))
                                                    } else {
                                                        setSelectedTables([...selectedTables, tableKey])
                                                    }
                                                }}
                                            >
                                                <div className="flex items-center gap-3">
                                                    <input
                                                        type="checkbox"
                                                        checked={isSelected}
                                                        onChange={() => {
                                                            if (isSelected) {
                                                                setSelectedTables(selectedTables.filter(t => t !== tableKey))
                                                            } else {
                                                                setSelectedTables([...selectedTables, tableKey])
                                                            }
                                                        }}
                                                        className="w-4 h-4 text-blue-600 rounded"
                                                        onClick={(e) => e.stopPropagation()}
                                                    />
                                                    <div className="flex-1">
                                                        <div className="flex items-center gap-2">
                                                            <h4 className="text-sm font-medium text-foreground">
                                                                {table.name}
                                                            </h4>
                                                            {spacesWithThisTable.length > 0 && (
                                                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400">
                                                                    In {spacesWithThisTable.length} space{spacesWithThisTable.length !== 1 ? 's' : ''}
                                                                </span>
                                                            )}
                                                        </div>
                                                        <p className="text-xs text-muted-foreground">
                                                            {table.schema || 'public'}
                                                            {table.rowCount !== null && table.rowCount !== undefined && (
                                                                <> • {table.rowCount.toLocaleString()} rows</>
                                                            )}
                                                        </p>
                                                        {spacesWithThisTable.length > 0 && (
                                                            <div className="mt-1 flex flex-wrap gap-1">
                                                                {spacesWithThisTable.map(space => (
                                                                    <span
                                                                        key={space.id}
                                                                        className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-muted-foreground"
                                                                    >
                                                                        {space.name}
                                                                    </span>
                                                                ))}
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                            </div>
                                        )
                                    })}
                                    </div>
                                )
                            })()}
                        </div>
                        
                        {/* Coluna Direita - Space Selection e Tabelas Selecionadas */}
                        <div className="flex-1 overflow-y-auto p-5">
                            <div className="mb-4">
                                <h3 className="text-sm font-semibold text-foreground mb-2">
                                    Assign to Space
                                </h3>
                                
                                {/* Space Selector */}
                                <div className="mb-4">
                                    <label className="text-xs font-medium text-foreground mb-2 block">
                                        Select Space
                                    </label>
                                    <div className="flex gap-2">
                                        <select
                                            value={selectedSpaceId}
                                            onChange={(e) => setSelectedSpaceId(e.target.value)}
                                            className={cn(
                                                "flex-1 h-9 px-3 rounded-lg text-sm border",
                                                isDark 
                                                    ? "bg-white/4 border-white/8 text-foreground" 
                                                    : "bg-white border-black/8 text-foreground",
                                                "appearance-none cursor-pointer"
                                            )}
                                        >
                                            <option value="">Select a space...</option>
                                            {spaces.map(space => (
                                                <option key={space.id} value={space.id}>
                                                    {space.name}
                                                </option>
                                            ))}
                                        </select>
                                        <button
                                            onClick={() => setShowCreateSpaceModal(true)}
                                            className={cn(
                                                "px-3 py-2 rounded-lg text-sm font-medium",
                                                "bg-primary hover:bg-primary/90 text-primary-foreground",
                                                "transition-colors flex items-center gap-2"
                                            )}
                                        >
                                            <Plus className="w-4 h-4" />
                                            New Space
                                        </button>
                                    </div>
                                </div>
                                
                                {/* Tabelas já atribuídas ao space selecionado */}
                                {selectedSpaceId && (() => {
                                    const selectedSpacePerm = spacePerms.find(p => p.space_id === selectedSpaceId)
                                    const existingTables = selectedSpacePerm?.table_access || []
                                    const selectedSpace = spaces.find(s => s.id === selectedSpaceId)
                                    
                                    return (
                                        <div className="mb-4">
                                            <div className="flex items-center justify-between mb-2">
                                                <p className="text-xs font-medium text-foreground">
                                                    Tables in "{selectedSpace?.name}" ({existingTables.length})
                                                </p>
                                            </div>
                                            {existingTables.length > 0 ? (
                                                <div className="space-y-2 max-h-48 overflow-y-auto border rounded-lg p-2 bg-gray-50 dark:bg-gray-900/30">
                                                    {existingTables.map(tableName => {
                                                        const fullTable = tables.find(t => t.name === tableName)
                                                        const tableKey = fullTable ? `${fullTable.schema || 'public'}.${tableName}` : tableName
                                                        const isSelected = selectedTables.includes(tableKey)
                                                        
                                                        return (
                                                            <div
                                                                key={tableName}
                                                                className={cn(
                                                                    "p-2 rounded border text-xs",
                                                                    "bg-white dark:bg-gray-800",
                                                                    "border-gray-200 dark:border-gray-700",
                                                                    isSelected && "border-blue-500 bg-blue-50 dark:bg-blue-900/20"
                                                                )}
                                                            >
                                                                <div className="flex items-center justify-between">
                                                                    <div>
                                                                        <p className="font-medium text-foreground">{tableName}</p>
                                                                        {fullTable && (
                                                                            <p className="text-[10px] text-muted-foreground">
                                                                                {fullTable.schema || 'public'}
{fullTable.rowCount !== null && fullTable.rowCount !== undefined && (
                                                                                    <> • {fullTable.rowCount.toLocaleString()} rows</>
                                                                                )}
                                                                            </p>
                                                                        )}
                                                                    </div>
                                                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400">
                                                                        Already assigned
                                                                    </span>
                                                                </div>
                                                            </div>
                                                        )
                                                    })}
                                                </div>
                                            ) : (
                                                <div className="text-xs text-muted-foreground text-center py-4 border rounded-lg bg-gray-50 dark:bg-gray-900/30">
                                                    No tables assigned to this space yet
                                                </div>
                                            )}
                                        </div>
                                    )
                                })()}
                                
                                {/* Selected Tables Preview */}
                                {selectedTables.length > 0 && selectedSpaceId && (() => {
                                    const selectedSpacePerm = spacePerms.find(p => p.space_id === selectedSpaceId)
                                    const existingTables = selectedSpacePerm?.table_access || []
                                    
                                    const newTables = selectedTables.filter(tableKey => {
                                        const tableName = tableKey.split('.')[1]
                                        return !existingTables.includes(tableName)
                                    })
                                    const alreadyAssignedTables = selectedTables.filter(tableKey => {
                                        const tableName = tableKey.split('.')[1]
                                        return existingTables.includes(tableName)
                                    })
                                    
                                    return (
                                        <div className="mb-4">
                                            <p className="text-xs font-medium text-foreground mb-2">
                                                Selected Tables ({selectedTables.length})
                                            </p>
                                            
                                            {newTables.length > 0 && (
                                                <div className="mb-3">
                                                    <p className="text-[10px] font-medium text-green-600 dark:text-green-400 mb-1">
                                                        New ({newTables.length})
                                                    </p>
                                                    <div className="space-y-2 max-h-32 overflow-y-auto">
                                                        {newTables.map(tableKey => {
                                                            const [schema, name] = tableKey.split('.')
                                                            return (
                                                                <div
                                                                    key={tableKey}
                                                                    className={cn(
                                                                        "p-2 rounded border",
                                                                        "bg-green-50 dark:bg-green-900/20",
                                                                        "border-green-200 dark:border-green-800"
                                                                    )}
                                                                >
                                                                    <div className="flex items-center justify-between">
                                                                        <div>
                                                                            <p className="text-xs font-medium text-foreground">{name}</p>
                                                                            <p className="text-[10px] text-muted-foreground">{schema}</p>
                                                                        </div>
                                                                        <button
                                                                            onClick={() => {
                                                                                setSelectedTables(selectedTables.filter(t => t !== tableKey))
                                                                            }}
                                                                            className="text-red-500 hover:text-red-700"
                                                                        >
                                                                            <X className="w-3 h-3" />
                                                                        </button>
                                                                    </div>
                                                                </div>
                                                            )
                                                        })}
                                                    </div>
                                                </div>
                                            )}
                                            
                                            {alreadyAssignedTables.length > 0 && (
                                                <div className="mb-3">
                                                    <p className="text-[10px] font-medium text-orange-600 dark:text-orange-400 mb-1">
                                                        Already Assigned ({alreadyAssignedTables.length}) - Will be skipped
                                                    </p>
                                                    <div className="space-y-2 max-h-32 overflow-y-auto">
                                                        {alreadyAssignedTables.map(tableKey => {
                                                            const [schema, name] = tableKey.split('.')
                                                            return (
                                                                <div
                                                                    key={tableKey}
                                                                    className={cn(
                                                                        "p-2 rounded border",
                                                                        "bg-orange-50 dark:bg-orange-900/20",
                                                                        "border-orange-200 dark:border-orange-800"
                                                                    )}
                                                                >
                                                                    <div className="flex items-center justify-between">
                                                                        <div>
                                                                            <p className="text-xs font-medium text-foreground">{name}</p>
                                                                            <p className="text-[10px] text-muted-foreground">{schema}</p>
                                                                        </div>
                                                                        <button
                                                                            onClick={() => {
                                                                                setSelectedTables(selectedTables.filter(t => t !== tableKey))
                                                                            }}
                                                                            className="text-red-500 hover:text-red-700"
                                                                        >
                                                                            <X className="w-3 h-3" />
                                                                        </button>
                                                                    </div>
                                                                </div>
                                                            )
                                                        })}
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    )
                                })()}
                                
                                {/* Assign Button */}
                                {selectedSpaceId && selectedTables.length > 0 && (() => {
                                    const selectedSpacePerm = spacePerms.find(p => p.space_id === selectedSpaceId)
                                    const existingTables = selectedSpacePerm?.table_access || []
                                    const newTables = selectedTables.filter(tableKey => {
                                        const tableName = tableKey.split('.')[1]
                                        return !existingTables.includes(tableName)
                                    })
                                    
                                    return newTables.length > 0 ? (
                                        <button
                                            onClick={async () => {
                                                try {
                                                    if (selectedSpacePerm) {
                                                        const currentTables = selectedSpacePerm.table_access || []
                                                        const newTableNames = newTables.map(t => t.split('.')[1])
                                                        const updatedTables = [...new Set([...currentTables, ...newTableNames])]
                                                        
                                                        await permissionsApi.updatePermission(selectedSpacePerm.id, {
                                                            access_level: 'custom',
                                                            table_access: updatedTables
                                                        })
                                                    } else {
                                                        await handleAssignToSpace(
                                                            conn.id,
                                                            selectedSpaceId,
                                                            'custom',
                                                            newTables.map(t => t.split('.')[1])
                                                        )
                                                    }
                                                    
                                                    await loadPermissions(conn.id)
                                                } catch (error) {
                                                    console.error('Error assigning tables:', error)
                                                    alert(`Error assigning tables: ${error instanceof Error ? error.message : 'Unknown error'}`)
                                                }
                                            }}
                                            className={cn(
                                                "w-full px-4 py-2 rounded-lg text-sm font-medium mb-4",
                                                "bg-primary hover:bg-primary/90 text-primary-foreground",
                                                "transition-colors"
                                            )}
                                        >
                                            Add {newTables.length} New Table{newTables.length !== 1 ? 's' : ''} to Space
                                        </button>
                                    ) : null
                                })()}
                            </div>
                        </div>
                    </div>
                    
                    {/* Footer com opção de criar conexão */}
                    <div className={cn(
                        "px-5 py-4 border-t flex-shrink-0",
                        isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
                    )}>
                        <div className="max-w-3xl mx-auto">
                            <div className="flex gap-3">
                                <button
                                    onClick={handleFinishConnection}
                                    className={cn(
                                        "flex-1 px-4 py-3 rounded-lg text-sm font-medium",
                                        "bg-primary hover:bg-primary/90 text-primary-foreground",
                                        "transition-colors"
                                    )}
                                >
                                    Create Connection
                                </button>
                            </div>
                        </div>
                    </div>
                    
                    {/* Create Space Modal */}
                    {showCreateSpaceModal && (
                        <AssignSpaceModal
                            isOpen={showCreateSpaceModal}
                            onClose={() => {
                                setShowCreateSpaceModal(false)
                                fetchSpaces()
                            }}
                            connectionId={conn.id}
                            spaces={spaces}
                            connection={conn}
                            onCreateSpace={handleCreateSpace}
                            onAssign={async (connectionId, spaceId, accessLevel, selectedTables) => {
                                await handleAssignToSpace(connectionId, spaceId, accessLevel, selectedTables)
                                await loadPermissions(connectionId)
                                setShowCreateSpaceModal(false)
                                setSelectedSpaceId(spaceId)
                                setSelectedTables([])
                                fetchSpaces()
                            }}
                            onFinish={async () => {
                                await loadPermissions(conn.id)
                            }}
                            isDark={isDark}
                        />
                    )}
                </div>
            )
        }

        // Se não está criando nova conexão, manter layout antigo (para quando visualizar tabelas de conexão existente)
        return (
            <div className="h-full flex flex-col">
                {/* Header */}
                <div className={cn(
                    "px-5 py-4 border-b flex-shrink-0 flex items-center justify-between",
                    isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
                )}>
                    <div>
                        <h2 className="text-lg font-semibold text-foreground">Tables</h2>
                        <p className="text-xs text-muted-foreground">
                            {conn.name} — {tables.length} table{tables.length === 1 ? '' : 's'}
                        </p>
                    </div>
                    <button
                        onClick={() => {
                            setViewMode('list')
                            setSelectedConnectionForTables(null)
                        }}
                        className={cn(
                            "px-3 py-2 rounded-lg text-sm",
                            "hover:bg-gray-100 dark:hover:bg-white/5",
                            "transition-colors"
                        )}
                    >
                        Back
                    </button>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto p-5">
                    {tables.length === 0 ? (
                        <div className="text-sm text-muted-foreground text-center py-12">
                            No tables available for this connection.
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                            {tables.map((table) => {
                                const tableKey = `${table.schema || 'public'}.${table.name}`
                                const isExpanded = expandedTable === tableKey
                                
                                return (
                                    <div
                                        key={tableKey}
                                        className={cn(
                                            "rounded-xl border transition-all duration-200 cursor-pointer",
                                            "bg-white dark:bg-gray-800",
                                            "border-gray-200 dark:border-gray-700",
                                            "hover:border-blue-300 dark:hover:border-blue-600",
                                            "hover:shadow-md",
                                            isExpanded && "border-blue-400 dark:border-blue-500 shadow-lg ring-2 ring-blue-100 dark:ring-blue-900/30"
                                        )}
                                        onClick={() => {
                                            setExpandedTable(isExpanded ? null : tableKey)
                                        }}
                                    >
                                        {/* Header - sempre visível */}
                                        <div className="p-4">
                                            <div className="flex items-center justify-between">
                                                <div className="flex-1 min-w-0">
                                                    <h3 className="text-sm font-semibold text-foreground truncate">
                                                        {table.name}
                                                    </h3>
                                                    <p className="text-xs text-muted-foreground mt-1">
                                                        {table.schema || 'public'}
                                                        {table.rowCount !== null && table.rowCount !== undefined && (
                                                            <> • {table.rowCount.toLocaleString()} rows</>
                                                        )}
                                                    </p>
                                                </div>
                                                <ChevronDown 
                                                    className={cn(
                                                        "w-4 h-4 text-muted-foreground transition-transform flex-shrink-0 ml-2",
                                                        isExpanded && "transform rotate-180"
                                                    )}
                                                />
                                            </div>
                                        </div>
                                        
                                        {/* Colunas - apenas quando expandido */}
                                        {isExpanded && table.columns && table.columns.length > 0 && (
                                            <div className="px-4 pb-4 border-t border-gray-200 dark:border-gray-700 pt-3 mt-2">
                                                <p className="text-xs font-semibold text-muted-foreground mb-3">
                                                    Columns ({table.columns.length})
                                                </p>
                                                <div className="space-y-1.5 max-h-64 overflow-y-auto">
                                                    {table.columns.map((col: any) => (
                                                        <div
                                                            key={col.name}
                                                            className={cn(
                                                                "px-2.5 py-1.5 rounded-md text-xs",
                                                                "bg-gray-50 dark:bg-gray-900/50",
                                                                "border border-gray-200 dark:border-gray-700"
                                                            )}
                                                        >
                                                            <div className="flex items-center justify-between">
                                                                <span className="font-medium text-foreground">
                                                                    {col.name}
                                                                </span>
                                                                <span className="text-[10px] text-muted-foreground ml-2">
                                                                    {col.type}
                                                                </span>
                                                            </div>
                                                            {!col.nullable && (
                                                                <span className="text-[10px] text-orange-600 dark:text-orange-400 mt-0.5 block">
                                                                    not null
                                                                </span>
                                                            )}
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                )
                            })}
                        </div>
                    )}
                </div>
            </div>
        )
    }
    
    // Render add connection view with 3 steps
    if (viewMode === 'add') {
        // Use connectors from backend if available, otherwise use local registry
        const availableConnectors = selectedConnectionType 
            ? (connectors.length > 0 
                ? connectors.filter(c => c.category === selectedConnectionType).map(apiConnector => {
                    // Convert API connector to ConnectorDefinition format
                    const localConnector = getConnectorById(apiConnector.id)
                    return localConnector || {
                        id: apiConnector.id,
                        name: apiConnector.name,
                        category: apiConnector.category as any,
                        description: apiConnector.description,
                        icon: iconMap[apiConnector.icon || 'database'] || iconMap.database,
                        fields: apiConnector.fields || [],
                        authMethods: apiConnector.auth_methods || [],
                        configSchema: apiConnector.config_schema,
                        syncFrequency: apiConnector.sync_frequency
                    }
                })
                : getConnectorsByCategory(selectedConnectionType))
            : []
        
        return (
            <div className="h-full flex flex-col min-h-0" style={{ height: '100%', maxHeight: '100%' }}>
                {/* Header with Back Button */}
                <div className={cn(
                    "px-5 py-4 border-b flex-shrink-0",
                    isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
                )}>
                    <div className="flex items-center gap-3 mb-4">
                        <button
                            onClick={async () => {
                                // Clean up temp connection if it exists
                                if (tempConnectionId) {
                                    try {
                                        await connectionsApi.deleteConnection(tempConnectionId)
                                    } catch (err) {
                                        console.warn('Failed to delete temp connection:', err)
                                    }
                                    setTempConnectionId(null)
                                }
                                setViewMode('list')
                                setAddConnectionStep(1)
                                setSelectedConnectionType(null)
                                setSelectedConnectorForAdd(null)
                                setFormData({ name: '', description: '' })
                                setTestResult(null)
                            }}
                            className={cn(
                                "p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-white/5 transition-colors"
                            )}
                        >
                            <ChevronLeft className="w-4 h-4" />
                        </button>
                        <div className="flex-1">
                            <h2 className="text-lg font-semibold text-foreground">
                                Add Connection
                            </h2>
                            <p className="text-xs text-muted-foreground">
                                Step {addConnectionStep} of 5
                            </p>
                        </div>
                    </div>
                    
                    {/* Progress Indicator */}
                    <div className="flex items-center justify-center gap-2 mb-4">
                        {[1, 2, 3, 4, 5].map((step) => (
                            <div key={step} className="flex items-center">
                                <div className={cn(
                                    "w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium transition-all",
                                    addConnectionStep >= step
                                        ? "bg-blue-500 text-white"
                                        : "bg-gray-200 dark:bg-gray-700 text-muted-foreground"
                                )}>
                                    {step}
                                </div>
                                {step < 5 && (
                                    <div className={cn(
                                        "w-8 h-0.5 mx-1 transition-all",
                                        addConnectionStep > step ? "bg-blue-500" : "bg-gray-200 dark:bg-gray-700"
                                    )} />
                                )}
                            </div>
                        ))}
                    </div>
                </div>
                
                {/* Step Content */}
                <div className="flex-1 overflow-y-auto p-5 min-h-0">
                    <div className="max-w-3xl mx-auto space-y-6">
                        {addConnectionStep === 1 && (
                            <>
                                <div>
                                    <label className="text-sm font-medium text-foreground mb-2 block">
                                        Connection Name <span className="text-red-500">*</span>
                                    </label>
                                    <Input
                                        value={formData.name || ''}
                                        onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                        placeholder="e.g., Production Database"
                                        className={cn(
                                            "h-10 text-sm",
                                            isDark 
                                                ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                                : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                                        )}
                                    />
                                </div>
                                
                                <div>
                                    <label className="text-sm font-medium text-foreground mb-2 block">
                                        Connection Type <span className="text-red-500">*</span>
                                    </label>
                                    <div className="grid grid-cols-3 gap-3">
                                        {(['database', 'document', 'api'] as const).map(type => {
                                            const Icon = type === 'database' ? Database : type === 'document' ? FileText : Globe
                                            return (
                                                <button
                                                    key={type}
                                                    onClick={() => setSelectedConnectionType(type)}
                                                    className={cn(
                                                        "p-4 rounded-lg border-2 transition-all",
                                                        selectedConnectionType === type
                                                            ? "border-blue-500 bg-blue-50 dark:bg-blue-900/20"
                                                            : "border-gray-200 dark:border-gray-700 hover:border-blue-300"
                                                    )}
                                                >
                                                    <Icon className={cn(
                                                        "w-8 h-8 mx-auto mb-2",
                                                        selectedConnectionType === type
                                                            ? "text-blue-600 dark:text-blue-400"
                                                            : "text-muted-foreground"
                                                    )} />
                                                    <p className={cn(
                                                        "text-sm font-medium",
                                                        selectedConnectionType === type
                                                            ? "text-blue-600 dark:text-blue-400"
                                                            : "text-foreground"
                                                    )}>
                                                        {type.charAt(0).toUpperCase() + type.slice(1)}
                                                    </p>
                                                </button>
                                            )
                                        })}
                                    </div>
                                </div>
                                
                                <div>
                                    <label className="text-sm font-medium text-foreground mb-2 block">
                                        Description
                                    </label>
                                    <textarea
                                        value={formData.description || ''}
                                        onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                                        placeholder="Optional description for this connection"
                                        rows={3}
                                        className={cn(
                                            "w-full rounded-lg text-sm p-3 resize-none",
                                            isDark 
                                                ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                                : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                                        )}
                                    />
                                </div>
                            </>
                        )}
                        
                        {addConnectionStep === 2 && selectedConnectionType && (
                            <>
                                <div>
                                    <h3 className="text-sm font-semibold text-foreground mb-4">
                                        Select a {selectedConnectionType} connector
                                    </h3>
                                    <div className="grid grid-cols-2 gap-4">
                                        {availableConnectors.map(connector => {
                                            const Icon = connector.icon
                                            return (
                                                <button
                                                    key={connector.id}
                                                    onClick={async () => {
                                                        // Clean up temp connection and test result when selecting a new connector
                                                        if (tempConnectionId) {
                                                            try {
                                                                await connectionsApi.deleteConnection(tempConnectionId)
                                                            } catch (err) {
                                                                console.warn('Failed to delete temp connection:', err)
                                                            }
                                                            setTempConnectionId(null)
                                                        }
                                                        setTestResult(null)
                                                        
                                                        setSelectedConnectorForAdd(connector)
                                                        setSelectedAuthMethod(connector.authMethods[0]?.type || '')
                                                        // Initialize form data
                                                        const initialData: Record<string, any> = { 
                                                            name: formData.name, 
                                                            description: formData.description 
                                                        }
                                                        connector.fields.forEach(field => {
                                                            initialData[field.key] = ''
                                                        })
                                                        connector.authMethods.forEach(auth => {
                                                            auth.fields.forEach(field => {
                                                                initialData[field.key] = ''
                                                            })
                                                        })
                                                        setFormData(initialData)
                                                    }}
                                                    className={cn(
                                                        "p-4 rounded-lg border-2 text-left transition-all",
                                                        selectedConnectorForAdd?.id === connector.id
                                                            ? "border-blue-500 bg-blue-50 dark:bg-blue-900/20"
                                                            : "border-gray-200 dark:border-gray-700 hover:border-blue-300"
                                                    )}
                                                >
                                                    <div className="flex items-start gap-3">
                                                        <div className={cn(
                                                            "w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0",
                                                            connector.category === 'database' && "bg-blue-100 dark:bg-blue-900/30",
                                                            connector.category === 'document' && "bg-green-100 dark:bg-green-900/30",
                                                            connector.category === 'api' && "bg-purple-100 dark:bg-purple-900/30"
                                                        )}>
                                                            <Icon className={cn(
                                                                "w-5 h-5",
                                                                connector.category === 'database' && "text-blue-600 dark:text-blue-400",
                                                                connector.category === 'document' && "text-green-600 dark:text-green-400",
                                                                connector.category === 'api' && "text-purple-600 dark:text-purple-400"
                                                            )} />
                                                        </div>
                                                        <div className="flex-1">
                                                            <h4 className="text-sm font-semibold text-foreground mb-1">
                                                                {connector.name}
                                                            </h4>
                                                            <p className="text-xs text-muted-foreground">
                                                                {connector.description}
                                                            </p>
                                                        </div>
                                                    </div>
                                                </button>
                                            )
                                        })}
                                    </div>
                                    
                                    {selectedConnectorForAdd && (
                                        <div className={cn(
                                            "mt-4 p-4 rounded-lg border",
                                            "bg-blue-50 dark:bg-blue-900/20",
                                            "border-blue-200 dark:border-blue-800"
                                        )}>
                                            <h4 className="text-sm font-semibold text-foreground mb-2">
                                                {selectedConnectorForAdd.name} - Setup Instructions
                                            </h4>
                                            <p className="text-xs text-muted-foreground mb-3">
                                                {selectedConnectorForAdd.description}
                                            </p>
                                            <div className="space-y-2">
                                                <p className="text-xs font-medium text-foreground">Required Fields:</p>
                                                <ul className="text-xs text-muted-foreground space-y-1 ml-4">
                                                    {selectedConnectorForAdd.fields.filter(f => f.required).map(field => (
                                                        <li key={field.key}>• {field.label}</li>
                                                    ))}
                                                </ul>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </>
                        )}
                        
                        {addConnectionStep === 3 && selectedConnectorForAdd && (
                            <>
                                <div>
                                    <h3 className="text-sm font-semibold text-foreground mb-4">
                                        Configure {selectedConnectorForAdd.name}
                                    </h3>
                                    
                                    <div className="space-y-4 border-t pt-6">
                                        <h4 className="text-sm font-semibold text-foreground mb-4">Connection Details</h4>
                                        <div className="grid grid-cols-2 gap-4">
                                            {selectedConnectorForAdd.fields.map(field => (
                                                <DynamicFormField
                                                    key={field.key}
                                                    field={field}
                                                    value={formData[field.key]}
                                                    onChange={(value) => setFormData({ ...formData, [field.key]: value })}
                                                    isDark={isDark}
                                                />
                                            ))}
                                        </div>
                                    </div>
                                    
                                    {selectedConnectorForAdd.authMethods.length > 0 && (
                                        <div className="space-y-4 border-t pt-6 mt-6">
                                            <h4 className="text-sm font-semibold text-foreground mb-4">Authentication</h4>
                                            <div className="space-y-4">
                                                <div>
                                                    <label className="text-sm font-medium text-foreground mb-2 block">
                                                        Authentication Method <span className="text-red-500">*</span>
                                                    </label>
                                                    <div className="relative">
                                                        <select
                                                            value={selectedAuthMethod}
                                                            onChange={(e) => {
                                                                setSelectedAuthMethod(e.target.value)
                                                                // Clear test result when auth method changes
                                                                setTestResult(null)
                                                            }}
                                                            className={cn(
                                                                "h-10 px-3 pr-8 rounded-lg text-sm border w-full",
                                                                isDark 
                                                                    ? "bg-white/4 border-white/8 text-foreground" 
                                                                    : "bg-white border-black/8 text-foreground",
                                                                "appearance-none cursor-pointer"
                                                            )}
                                                        >
                                                            {selectedConnectorForAdd.authMethods.map(method => (
                                                                <option key={method.type} value={method.type}>{method.label}</option>
                                                            ))}
                                                        </select>
                                                        <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                                                    </div>
                                                </div>
                                                {selectedConnectorForAdd.authMethods.find(m => m.type === selectedAuthMethod)?.fields.map(field => (
                                                    <DynamicFormField
                                                        key={field.key}
                                                        field={field}
                                                        value={formData[field.key]}
                                                        onChange={(value) => setFormData({ ...formData, [field.key]: value })}
                                                        isDark={isDark}
                                                    />
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                                
                                {/* Test Result */}
                                {testResult && (
                                    <div className={cn(
                                        "p-4 rounded-lg border",
                                        testResult.success
                                            ? "bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800"
                                            : "bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800"
                                    )}>
                                        <div className="flex items-center gap-2">
                                            {testResult.success ? (
                                                <CheckCircle2 className="w-5 h-5 text-green-600 dark:text-green-400" />
                                            ) : (
                                                <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
                                            )}
                                            <p className={cn(
                                                "text-sm font-medium",
                                                testResult.success ? "text-green-700 dark:text-green-300" : "text-red-700 dark:text-red-300"
                                            )}>
                                                {testResult.message}
                                            </p>
                                        </div>
                                    </div>
                                )}
                            </>
                        )}
                        
                        {/* Step 4: Assign Tables to Spaces/Crews (Optional) */}
                        {addConnectionStep === 4 && tempConnectionId && (
                            <>
                                {(() => {
                                    const conn = connections.find(c => c.id === tempConnectionId)
                                    const tables = conn?.metadata?.tables || []
                                    
                                    if (tables.length === 0) {
                                        return (
                                            <div className={cn(
                                                "p-4 rounded-lg border",
                                                "bg-yellow-50 dark:bg-yellow-900/20",
                                                "border-yellow-200 dark:border-yellow-800"
                                            )}>
                                                <p className="text-sm text-yellow-700 dark:text-yellow-300">
                                                    No tables discovered yet. Please sync tables first.
                                                </p>
                                            </div>
                                        )
                                    }
                                    
                                    const filteredTables = tables.filter(table => {
                                        const fullName = `${table.schema ? `${table.schema}.` : ''}${table.name}`
                                        if (!tableSearchQuery) return true
                                        return fullName.toLowerCase().includes(tableSearchQuery.toLowerCase()) ||
                                               table.name.toLowerCase().includes(tableSearchQuery.toLowerCase()) ||
                                               (table.schema && table.schema.toLowerCase().includes(tableSearchQuery.toLowerCase()))
                                    })
                                    
                                    // Get assigned tables for selected space
                                    const assignedTablesForSelectedSpace = selectedSpaceForAssignment 
                                        ? (assignedTablesToSpaces[selectedSpaceForAssignment]?.tables || [])
                                        : []
                                    
                                    // Get assigned tables for selected crew
                                    const assignedTablesForSelectedCrew = selectedCrewForAssignment 
                                        ? (assignedTablesToCrews[selectedCrewForAssignment]?.tables || [])
                                        : []
                                    
                                    return (
                                        <div className="space-y-4">
                                            <div className="mb-2">
                                                <h3 className="text-sm font-semibold text-foreground mb-1">
                                                    Assign Tables to Spaces or Crews (Optional)
                                                </h3>
                                                <p className="text-xs text-muted-foreground">
                                                    {tables.length} table{tables.length !== 1 ? 's' : ''} discovered. Select tables and assign them to Spaces or Crews, or skip this step.
                                                </p>
                                            </div>
                                            
                                            <div className="grid grid-cols-2 gap-6">
                                                {/* Left Column: Table Selection */}
                                                <div className="space-y-4">
                                                    <div>
                                                        <h4 className="text-sm font-semibold text-foreground mb-2">
                                                            Select tables to assign
                                                        </h4>
                                                        <div className="relative mb-3">
                                                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                                                            <Input
                                                                placeholder="Search tables..."
                                                                value={tableSearchQuery}
                                                                onChange={(e) => setTableSearchQuery(e.target.value)}
                                                                className={cn(
                                                                    "pl-9 h-9 text-sm",
                                                                    isDark 
                                                                        ? "bg-white/4 border-white/8" 
                                                                        : "bg-white border-black/8"
                                                                )}
                                                            />
                                                        </div>
                                                        <div className="border rounded-lg p-3 max-h-[400px] overflow-y-auto">
                                                            {filteredTables.length === 0 ? (
                                                                <p className="text-xs text-muted-foreground text-center py-4">
                                                                    {tableSearchQuery ? 'No tables found matching your search' : 'No tables available'}
                                                                </p>
                                                            ) : (
                                                                <div className="space-y-2">
                                                                    {filteredTables.map((table, idx) => {
                                                                        const fullName = `${table.schema ? `${table.schema}.` : ''}${table.name}`
                                                                        const isSelected = selectedTablesForAssignment.includes(fullName)
                                                                        return (
                                                                            <label
                                                                                key={idx}
                                                                                className={cn(
                                                                                    "flex items-center gap-2 p-2 rounded hover:bg-gray-50 dark:hover:bg-white/5 cursor-pointer",
                                                                                    isSelected && "bg-blue-50 dark:bg-blue-900/20"
                                                                                )}
                                                                            >
                                                                                <input
                                                                                    type="checkbox"
                                                                                    checked={isSelected}
                                                                                    onChange={(e) => {
                                                                                        if (e.target.checked) {
                                                                                            setSelectedTablesForAssignment(prev => [...prev, fullName])
                                                                                        } else {
                                                                                            setSelectedTablesForAssignment(prev => prev.filter(t => t !== fullName))
                                                                                        }
                                                                                    }}
                                                                                    className="w-4 h-4 rounded border-gray-300 text-primary focus:ring-primary"
                                                                                />
                                                                                <div className="flex-1 min-w-0">
                                                                                    <div className="text-sm font-medium text-foreground truncate">
                                                                                        {table.name}
                                                                                    </div>
                                                                                    {table.schema && (
                                                                                        <div className="text-xs text-muted-foreground">
                                                                                            {table.schema}
                                                                                        </div>
                                                                                    )}
                                                                                </div>
                                                                            </label>
                                                                        )
                                                                    })}
                                                                </div>
                                                            )}
                                                        </div>
                                                    </div>
                                                </div>
                                                
                                                {/* Right Column: Space/Crew Assignment */}
                                                <div className="space-y-6">
                                                    {/* Assign to Space */}
                                                    <div className="border rounded-lg p-4">
                                                        <h4 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
                                                            <Globe className="w-4 h-4" />
                                                            Assign to Space
                                                        </h4>
                                                        <div className="space-y-3">
                                                            <div className="flex items-center gap-2">
                                                                <div className="relative flex-1">
                                                                    <select
                                                                        value={selectedSpaceForAssignment}
                                                                        onChange={(e) => {
                                                                            setSelectedSpaceForAssignment(e.target.value)
                                                                            setSelectedCrewForAssignment('')
                                                                        }}
                                                                        className={cn(
                                                                            "w-full h-9 px-3 pr-8 rounded-lg text-sm border",
                                                                            isDark 
                                                                                ? "bg-white/4 border-white/8 text-foreground" 
                                                                                : "bg-white border-black/8 text-foreground",
                                                                            "appearance-none cursor-pointer"
                                                                        )}
                                                                    >
                                                                        <option value="">Select Space</option>
                                                                        {spaces.map(space => (
                                                                            <option key={space.id} value={space.id}>
                                                                                {space.name}
                                                                            </option>
                                                                        ))}
                                                                    </select>
                                                                    <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                                                                </div>
                                                                <button
                                                                    onClick={() => setShowCreateSpaceModal(true)}
                                                                    className={cn(
                                                                        "px-3 py-1.5 rounded-lg text-xs font-medium",
                                                                        "bg-primary hover:bg-primary/90 text-primary-foreground",
                                                                        "transition-colors flex items-center gap-1"
                                                                    )}
                                                                >
                                                                    <Plus className="w-3 h-3" />
                                                                    New Space
                                                                </button>
                                                            </div>
                                                            
                                                            {selectedSpaceForAssignment && (
                                                                <div className="border rounded-lg p-3 bg-gray-50 dark:bg-gray-900/20">
                                                                    <div className="flex items-center justify-between mb-2">
                                                                        <span className="text-sm font-medium text-foreground">
                                                                            {spaces.find(s => s.id === selectedSpaceForAssignment)?.name || 'Unknown'}
                                                                        </span>
                                                                        <span className="text-xs text-muted-foreground">
                                                                            {assignedTablesForSelectedSpace.length} table{assignedTablesForSelectedSpace.length !== 1 ? 's' : ''}
                                                                        </span>
                                                                    </div>
                                                                    {assignedTablesForSelectedSpace.length === 0 ? (
                                                                        <p className="text-xs text-muted-foreground">
                                                                            No tables assigned to this space yet.
                                                                        </p>
                                                                    ) : (
                                                                        <div className="space-y-1 max-h-32 overflow-y-auto">
                                                                            {assignedTablesForSelectedSpace.map((tableName, idx) => (
                                                                                <div key={idx} className="text-xs text-foreground flex items-center gap-2">
                                                                                    <Table className="w-3 h-3" />
                                                                                    {tableName}
                                                                                </div>
                                                                            ))}
                                                                        </div>
                                                                    )}
                                                                    {selectedTablesForAssignment.length > 0 && (
                                                                        <button
                                                                            onClick={() => {
                                                                                if (selectedSpaceForAssignment) {
                                                                                    setAssignedTablesToSpaces(prev => ({
                                                                                        ...prev,
                                                                                        [selectedSpaceForAssignment]: {
                                                                                            spaceId: selectedSpaceForAssignment,
                                                                                            tables: [...new Set([...assignedTablesForSelectedSpace, ...selectedTablesForAssignment])]
                                                                                        }
                                                                                    }))
                                                                                    setSelectedTablesForAssignment([])
                                                                                }
                                                                            }}
                                                                            className={cn(
                                                                                "mt-2 w-full px-3 py-1.5 rounded-lg text-xs font-medium",
                                                                                "bg-primary hover:bg-primary/90 text-primary-foreground",
                                                                                "transition-colors"
                                                                            )}
                                                                        >
                                                                            Assign {selectedTablesForAssignment.length} Selected Table{selectedTablesForAssignment.length !== 1 ? 's' : ''}
                                                                        </button>
                                                                    )}
                                                                </div>
                                                            )}
                                                        </div>
                                                    </div>
                                                    
                                                    {/* Assign to Crew */}
                                                    <div className="border rounded-lg p-4">
                                                        <h4 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
                                                            <Users className="w-4 h-4" />
                                                            Assign to Crew
                                                        </h4>
                                                        <div className="space-y-3">
                                                            <div className="relative">
                                                                <select
                                                                    value={selectedCrewForAssignment}
                                                                    onChange={(e) => {
                                                                        setSelectedCrewForAssignment(e.target.value)
                                                                        setSelectedSpaceForAssignment('')
                                                                    }}
                                                                    className={cn(
                                                                        "w-full h-9 px-3 pr-8 rounded-lg text-sm border",
                                                                        isDark 
                                                                            ? "bg-white/4 border-white/8 text-foreground" 
                                                                            : "bg-white border-black/8 text-foreground",
                                                                        "appearance-none cursor-pointer"
                                                                    )}
                                                                >
                                                                    <option value="">Select Crew</option>
                                                                    {crews.map(crew => (
                                                                        <option key={crew.id} value={crew.id}>
                                                                            {crew.name}
                                                                        </option>
                                                                    ))}
                                                                </select>
                                                                <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                                                            </div>
                                                            
                                                            {selectedCrewForAssignment && (
                                                                <div className="border rounded-lg p-3 bg-gray-50 dark:bg-gray-900/20">
                                                                    <div className="flex items-center justify-between mb-2">
                                                                        <span className="text-sm font-medium text-foreground">
                                                                            {crews.find(c => c.id === selectedCrewForAssignment)?.name || 'Unknown'}
                                                                        </span>
                                                                        <span className="text-xs text-muted-foreground">
                                                                            {assignedTablesForSelectedCrew.length} table{assignedTablesForSelectedCrew.length !== 1 ? 's' : ''}
                                                                        </span>
                                                                    </div>
                                                                    {assignedTablesForSelectedCrew.length === 0 ? (
                                                                        <p className="text-xs text-muted-foreground">
                                                                            No tables assigned to this crew yet.
                                                                        </p>
                                                                    ) : (
                                                                        <div className="space-y-1 max-h-32 overflow-y-auto">
                                                                            {assignedTablesForSelectedCrew.map((tableName, idx) => (
                                                                                <div key={idx} className="text-xs text-foreground flex items-center gap-2">
                                                                                    <Table className="w-3 h-3" />
                                                                                    {tableName}
                                                                                </div>
                                                                            ))}
                                                                        </div>
                                                                    )}
                                                                    {selectedTablesForAssignment.length > 0 && (
                                                                        <button
                                                                            onClick={() => {
                                                                                if (selectedCrewForAssignment) {
                                                                                    setAssignedTablesToCrews(prev => ({
                                                                                        ...prev,
                                                                                        [selectedCrewForAssignment]: {
                                                                                            crewId: selectedCrewForAssignment,
                                                                                            tables: [...new Set([...assignedTablesForSelectedCrew, ...selectedTablesForAssignment])]
                                                                                        }
                                                                                    }))
                                                                                    setSelectedTablesForAssignment([])
                                                                                }
                                                                            }}
                                                                            className={cn(
                                                                                "mt-2 w-full px-3 py-1.5 rounded-lg text-xs font-medium",
                                                                                "bg-primary hover:bg-primary/90 text-primary-foreground",
                                                                                "transition-colors"
                                                                            )}
                                                                        >
                                                                            Assign {selectedTablesForAssignment.length} Selected Table{selectedTablesForAssignment.length !== 1 ? 's' : ''}
                                                                        </button>
                                                                    )}
                                                                </div>
                                                            )}
                                                        </div>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    )
                                })()}
                            </>
                        )}
                        
                        {/* Step 5: Overview and Create Connection */}
                        {addConnectionStep === 5 && tempConnectionId && (
                            <>
                                {(() => {
                                    const conn = connections.find(c => c.id === tempConnectionId)
                                    const tables = conn?.metadata?.tables || []
                                    const connector = selectedConnectorForAdd || getConnectorById(conn?.connectorId || '')
                                    
                                    // Get all assigned spaces and crews
                                    const assignedSpaces = Object.entries(assignedTablesToSpaces).map(([spaceId, assignment]) => {
                                        const space = spaces.find(s => s.id === spaceId)
                                        return { space, tables: assignment.tables }
                                    }).filter(item => item.space)
                                    
                                    const assignedCrews = Object.entries(assignedTablesToCrews).map(([crewId, assignment]) => {
                                        const crew = crews.find(c => c.id === crewId)
                                        return { crew, tables: assignment.tables }
                                    }).filter(item => item.crew)
                                    
                                    return (
                                        <div className="space-y-6">
                                            <div className="mb-4">
                                                <h3 className="text-sm font-semibold text-foreground mb-1">
                                                    Connection Overview
                                                </h3>
                                                <p className="text-xs text-muted-foreground">
                                                    Review your connection details and assignments before creating the connection.
                                                </p>
                                            </div>
                                            
                                            {/* Connection Details */}
                                            <div className="border rounded-lg p-4 space-y-4">
                                                <h4 className="text-sm font-semibold text-foreground">Connection Details</h4>
                                                <div className="grid grid-cols-2 gap-4">
                                                    <div>
                                                        <p className="text-xs text-muted-foreground mb-1">Name</p>
                                                        <p className="text-sm font-medium text-foreground">{formData.name}</p>
                                                    </div>
                                                    <div>
                                                        <p className="text-xs text-muted-foreground mb-1">Type</p>
                                                        <p className="text-sm font-medium text-foreground capitalize">{selectedConnectionType}</p>
                                                    </div>
                                                    <div>
                                                        <p className="text-xs text-muted-foreground mb-1">Connector</p>
                                                        <p className="text-sm font-medium text-foreground">{connector?.name || 'Unknown'}</p>
                                                    </div>
                                                    {formData.description && (
                                                        <div>
                                                            <p className="text-xs text-muted-foreground mb-1">Description</p>
                                                            <p className="text-sm text-foreground">{formData.description}</p>
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                            
                                            {/* Discovered Tables */}
                                            <div className="border rounded-lg p-4">
                                                <h4 className="text-sm font-semibold text-foreground mb-3">
                                                    Discovered Tables ({tables.length})
                                                </h4>
                                                {tables.length === 0 ? (
                                                    <p className="text-xs text-muted-foreground">No tables discovered.</p>
                                                ) : (
                                                    <div className="max-h-48 overflow-y-auto space-y-2">
                                                        {tables.map((table, idx) => (
                                                            <div key={idx} className="flex items-center gap-2 text-sm text-foreground">
                                                                <Table className="w-4 h-4 text-muted-foreground" />
                                                                <span>{table.schema ? `${table.schema}.` : ''}{table.name}</span>
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                            
                                            {/* Assigned to Spaces */}
                                            {assignedSpaces.length > 0 && (
                                                <div className="border rounded-lg p-4">
                                                    <h4 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
                                                        <Globe className="w-4 h-4" />
                                                        Assigned to Spaces ({assignedSpaces.length})
                                                    </h4>
                                                    <div className="space-y-3">
                                                        {assignedSpaces.map(({ space, tables: assignedTables }, idx) => (
                                                            <div key={idx} className="border rounded-lg p-3 bg-gray-50 dark:bg-gray-900/20">
                                                                <div className="flex items-center justify-between mb-2">
                                                                    <span className="text-sm font-medium text-foreground">{space?.name}</span>
                                                                    <span className="text-xs text-muted-foreground">
                                                                        {assignedTables.length} table{assignedTables.length !== 1 ? 's' : ''}
                                                                    </span>
                                                                </div>
                                                                <div className="space-y-1 max-h-24 overflow-y-auto">
                                                                    {assignedTables.map((tableName, tableIdx) => (
                                                                        <div key={tableIdx} className="text-xs text-foreground flex items-center gap-2">
                                                                            <Table className="w-3 h-3" />
                                                                            {tableName}
                                                                        </div>
                                                                    ))}
                                                                </div>
                                                            </div>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}
                                            
                                            {/* Assigned to Crews */}
                                            {assignedCrews.length > 0 && (
                                                <div className="border rounded-lg p-4">
                                                    <h4 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
                                                        <Users className="w-4 h-4" />
                                                        Assigned to Crews ({assignedCrews.length})
                                                    </h4>
                                                    <div className="space-y-3">
                                                        {assignedCrews.map(({ crew, tables: assignedTables }, idx) => (
                                                            <div key={idx} className="border rounded-lg p-3 bg-gray-50 dark:bg-gray-900/20">
                                                                <div className="flex items-center justify-between mb-2">
                                                                    <span className="text-sm font-medium text-foreground">{crew?.name}</span>
                                                                    <span className="text-xs text-muted-foreground">
                                                                        {assignedTables.length} table{assignedTables.length !== 1 ? 's' : ''}
                                                                    </span>
                                                                </div>
                                                                <div className="space-y-1 max-h-24 overflow-y-auto">
                                                                    {assignedTables.map((tableName, tableIdx) => (
                                                                        <div key={tableIdx} className="text-xs text-foreground flex items-center gap-2">
                                                                            <Table className="w-3 h-3" />
                                                                            {tableName}
                                                                        </div>
                                                                    ))}
                                                                </div>
                                                            </div>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}
                                            
                                            {assignedSpaces.length === 0 && assignedCrews.length === 0 && (
                                                <div className="border rounded-lg p-4 bg-gray-50 dark:bg-gray-900/20">
                                                    <p className="text-xs text-muted-foreground text-center">
                                                        No tables assigned to Spaces or Crews. You can assign them later.
                                                    </p>
                                                </div>
                                            )}
                                        </div>
                                    )
                                })()}
                            </>
                        )}
                    </div>
                </div>
                
                {/* Actions - Fixed at bottom, outside scroll */}
                <div className={cn(
                    "px-5 py-4 border-t flex-shrink-0 sticky bottom-0 z-10",
                    isDark ? "border-white/5 bg-gray-900/20 backdrop-blur-sm" : "border-black/5 bg-gray-50/50 backdrop-blur-sm"
                )}>
                    <div className="max-w-3xl mx-auto flex items-center justify-end gap-3">
                        {addConnectionStep > 1 && (
                            <button
                                onClick={async () => {
                                    if (addConnectionStep === 2) {
                                        setAddConnectionStep(1)
                                        setSelectedConnectorForAdd(null)
                                        // Clean up temp connection and test result when going back from step 3
                                        if (tempConnectionId) {
                                            try {
                                                await connectionsApi.deleteConnection(tempConnectionId)
                                            } catch (err) {
                                                console.warn('Failed to delete temp connection:', err)
                                            }
                                            setTempConnectionId(null)
                                        }
                                        setTestResult(null)
                                    } else if (addConnectionStep === 3) {
                                        setAddConnectionStep(2)
                                        // Clean up temp connection and test result when going back from step 3
                                        if (tempConnectionId) {
                                            try {
                                                await connectionsApi.deleteConnection(tempConnectionId)
                                            } catch (err) {
                                                console.warn('Failed to delete temp connection:', err)
                                            }
                                            setTempConnectionId(null)
                                        }
                                        setTestResult(null)
                                    } else if (addConnectionStep === 4) {
                                        setAddConnectionStep(3)
                                    } else if (addConnectionStep === 5) {
                                        setAddConnectionStep(4)
                                    }
                                }}
                                className={cn(
                                    "px-4 py-2 rounded-lg text-sm font-medium",
                                    "hover:bg-gray-100 dark:hover:bg-gray-700",
                                    "transition-colors"
                                )}
                            >
                                Back
                            </button>
                        )}
                        {addConnectionStep === 4 ? (
                            <>
                                <button
                                    onClick={() => {
                                        // Skip Step 4 - go directly to overview
                                        setAddConnectionStep(5)
                                    }}
                                    className={cn(
                                        "px-4 py-2 rounded-lg text-sm font-medium",
                                        "bg-gray-500 hover:bg-gray-600 text-white",
                                        "transition-colors"
                                    )}
                                >
                                    Skip
                                </button>
                                <button
                                    onClick={() => {
                                        // Go to Step 5 (Overview)
                                        setAddConnectionStep(5)
                                    }}
                                    className={cn(
                                        "px-4 py-2 rounded-lg text-sm font-medium",
                                        "bg-primary hover:bg-primary/90 text-primary-foreground",
                                        "transition-colors"
                                    )}
                                >
                                    Overview
                                </button>
                            </>
                        ) : addConnectionStep === 5 ? (
                            <button
                                onClick={async () => {
                                    // Finalize connection and assign tables to Spaces/Crews
                                    if (tempConnectionId) {
                                        try {
                                            // Assign tables to Spaces
                                            for (const [spaceId, assignment] of Object.entries(assignedTablesToSpaces)) {
                                                const tableNames = assignment.tables.map(t => {
                                                    const parts = t.split('.')
                                                    return parts.length > 1 ? parts[1] : parts[0]
                                                })
                                                await handleAssignToSpace(
                                                    tempConnectionId,
                                                    spaceId,
                                                    'custom',
                                                    tableNames
                                                )
                                            }
                                            
                                            // Assign tables to Crews
                                            for (const [crewId, assignment] of Object.entries(assignedTablesToCrews)) {
                                                const tableNames = assignment.tables.map(t => {
                                                    const parts = t.split('.')
                                                    return parts.length > 1 ? parts[1] : parts[0]
                                                })
                                                await permissionsApi.createConnectionPermission(tempConnectionId, {
                                                    crew_id: crewId,
                                                    access_level: 'custom',
                                                    table_access: tableNames
                                                })
                                            }
                                            
                                            // Finalize connection
                                            await handleFinishConnection()
                                        } catch (err) {
                                            console.error('Error assigning tables:', err)
                                            setError(err instanceof Error ? err.message : 'Failed to assign tables')
                                        }
                                    }
                                }}
                                className={cn(
                                    "px-4 py-2 rounded-lg text-sm font-medium",
                                    "bg-primary hover:bg-primary/90 text-primary-foreground",
                                    "transition-colors"
                                )}
                            >
                                Create Connection
                            </button>
                        ) : addConnectionStep < 3 ? (
                            <button
                                onClick={() => {
                                    if (addConnectionStep === 1) {
                                        if (formData.name && selectedConnectionType) {
                                            setAddConnectionStep(2)
                                        }
                                    } else if (addConnectionStep === 2) {
                                        if (selectedConnectorForAdd) {
                                            setAddConnectionStep(3)
                                        }
                                    }
                                }}
                                disabled={
                                    (addConnectionStep === 1 && (!formData.name || !selectedConnectionType)) ||
                                    (addConnectionStep === 2 && !selectedConnectorForAdd)
                                }
                                className={cn(
                                    "px-4 py-2 rounded-lg text-sm font-medium",
                                    "bg-primary hover:bg-primary/90 text-primary-foreground",
                                    "disabled:opacity-50 disabled:cursor-not-allowed",
                                    "transition-colors"
                                )}
                            >
                                Next
                            </button>
                        ) : (
                            <>
                                <button
                                    onClick={handleTestConnection}
                                    disabled={testingConnection !== null || !isFormValid()}
                                    className={cn(
                                        "px-4 py-2 rounded-lg text-sm font-medium",
                                        "bg-gray-500 hover:bg-gray-600 text-white",
                                        "disabled:opacity-50 disabled:cursor-not-allowed",
                                        "transition-colors flex items-center gap-2"
                                    )}
                                >
                                    {testingConnection && <RefreshCw className="w-4 h-4 animate-spin" />}
                                    {testingConnection ? 'Testing...' : 'Test Connection'}
                                </button>
                                <button
                                    onClick={() => {
                                        const connectionId = editingConnection || tempConnectionId
                                        if (connectionId) {
                                            handleSyncTables(connectionId)
                                        }
                                    }}
                                    disabled={syncingConnection !== null || !isFormValid() || !testResult?.success}
                                    className={cn(
                                        "px-4 py-2 rounded-lg text-sm font-medium",
                                        "bg-primary hover:bg-primary/90 text-primary-foreground",
                                        "disabled:opacity-50 disabled:cursor-not-allowed",
                                        "transition-colors flex items-center gap-2"
                                    )}
                                >
                                    {syncingConnection ? (
                                        <>
                                            <RefreshCw className="w-4 h-4 animate-spin" />
                                            Discovering Tables...
                                        </>
                                    ) : (
                                        <>
                                            <Table className="w-4 h-4" />
                                            Sync Tables
                                        </>
                                    )}
                                </button>
                            </>
                        )}
                    </div>
                </div>
            </div>
        )
    }
    
    // Render connection dashboard view (when editing existing connection)
    if (viewMode === 'detail' && editingConnection) {
        const conn = connections.find(c => c.id === editingConnection)
        if (!conn) {
            setViewMode('list')
            setEditingConnection(null)
            return null
        }
        
        const connector = getConnectorById(conn.connectorId)
        const tables = conn.metadata?.tables || []
        const lastSyncDate = conn.lastSync ? new Date(conn.lastSync) : null
        const connPermissions = getConnectionPermissions(conn.id)
        const spacePerms = connPermissions.filter(p => p.space_id)
        const crewPerms = connPermissions.filter(p => p.crew_id)
        
        return (
            <div className="h-full flex flex-col">
                {/* Header */}
                <div className={cn(
                    "px-5 py-4 border-b flex-shrink-0",
                    isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
                )}>
                    <div className="flex items-center justify-between mb-4">
                        <div className="flex items-center gap-3">
                            <button
                                onClick={() => {
                                    setViewMode('list')
                                    setEditingConnection(null)
                                    setConnectionDashboardTab('tables')
                                    setDeleteModalOpen(false)
                                    setItemToDelete(null)
                                }}
                                className={cn(
                                    "p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-white/5 transition-colors"
                                )}
                            >
                                <ChevronLeft className="w-4 h-4" />
                            </button>
                            <div>
                                <h2 className="text-lg font-semibold text-foreground">{conn.name}</h2>
                                <p className="text-xs text-muted-foreground">
                                    {connector?.name || conn.connectorId} • {conn.status || 'active'}
                                </p>
                            </div>
                        </div>
                        
                        {/* Quick Actions */}
                        <div className="flex items-center gap-2">
                            <button
                                onClick={() => handleSyncNow(conn.id)}
                                className={cn(
                                    "px-3 py-2 rounded-lg text-sm font-medium",
                                    "bg-primary hover:bg-primary/90 text-primary-foreground",
                                    "transition-colors flex items-center gap-2"
                                )}
                            >
                                <RefreshCw className="w-4 h-4" />
                                Re-sync
                            </button>
                            <button
                                onClick={() => {
                                    setItemToDelete({ id: conn.id, name: conn.name })
                                    setDeleteModalOpen(true)
                                }}
                                className={cn(
                                    "px-3 py-2 rounded-lg text-sm font-medium",
                                    "bg-red-500 hover:bg-red-600 text-white",
                                    "transition-colors flex items-center gap-2"
                                )}
                            >
                                <Trash2 className="w-4 h-4" />
                                Delete
                            </button>
                        </div>
                    </div>
                    
                    {/* Error Message */}
                    {error && (
                        <div className="mb-4 p-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
                            <div className="flex items-center gap-2">
                                <AlertCircle className="w-5 h-5 text-red-500" />
                                <p className="text-sm text-red-700 dark:text-red-300 flex-1">{error}</p>
                                <button
                                    onClick={() => setError(null)}
                                    className="text-red-500 hover:text-red-700"
                                >
                                    <X className="w-4 h-4" />
                                </button>
                            </div>
                        </div>
                    )}
                    
                    {/* Tabs */}
                    <div className="flex gap-2 border-b border-gray-200 dark:border-gray-700">
                        {[
                            { id: 'tables', label: `Tables & Permissions (${tables.length})`, icon: Table },
                            { id: 'settings', label: 'Settings', icon: Settings }
                        ].map(tab => {
                            const Icon = tab.icon
                            return (
                                <button
                                    key={tab.id}
                                    onClick={() => setConnectionDashboardTab(tab.id as any)}
                                    className={cn(
                                        "px-4 py-2 text-sm font-medium border-b-2 transition-colors flex items-center gap-2",
                                        connectionDashboardTab === tab.id
                                            ? "border-blue-500 text-blue-600 dark:text-blue-400"
                                            : "border-transparent text-muted-foreground hover:text-foreground"
                                    )}
                                >
                                    <Icon className="w-4 h-4" />
                                    {tab.label}
                                </button>
                            )
                        })}
                    </div>
                </div>
                
                {/* Tab Content */}
                <div className="flex-1 overflow-hidden flex flex-col">
                    {connectionDashboardTab === 'tables' && (
                        <div className="flex-1 flex overflow-hidden">
                            {/* Coluna Esquerda - Todas as Tabelas */}
                            <div className="flex-1 border-r border-gray-200 dark:border-gray-700 overflow-y-auto p-5">
                                <div className="mb-4">
                                    <h3 className="text-sm font-semibold text-foreground mb-2">
                                        Available Tables ({tables.length})
                                    </h3>
                                    <p className="text-xs text-muted-foreground mb-3">
                                        Select tables to assign to a space
                                    </p>
                                    
                                    {/* Search Bar */}
                                    <div className="relative">
                                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                                        <Input
                                            type="text"
                                            placeholder="Search tables..."
                                            value={tableSearchQuery}
                                            onChange={(e) => setTableSearchQuery(e.target.value)}
                                            className={cn(
                                                "pl-9 h-9 text-sm",
                                                isDark 
                                                    ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                                    : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                                            )}
                                        />
                                    </div>
                                </div>
                                
                                {(() => {
                                    // Filtrar tabelas baseado na busca
                                    const filteredTables = tables.filter(table => {
                                        if (!tableSearchQuery.trim()) return true
                                        const query = tableSearchQuery.toLowerCase()
                                        return table.name.toLowerCase().includes(query) || 
                                               (table.schema || 'public').toLowerCase().includes(query)
                                    })
                                    
                                    return filteredTables.length === 0 ? (
                                        <div className="text-sm text-muted-foreground text-center py-12">
                                            {tableSearchQuery ? `No tables found matching "${tableSearchQuery}"` : 'No tables available for this connection.'}
                                        </div>
                                    ) : (
                                        <div className="space-y-2">
                                            {filteredTables.map((table) => {
                                            const tableKey = `${table.schema || 'public'}.${table.name}`
                                            const isSelected = selectedTables.includes(tableKey)
                                            
                                            // Encontrar quais spaces já têm esta tabela
                                            const spacesWithThisTable = spacePerms
                                                .filter(perm => perm.table_access?.includes(table.name))
                                                .map(perm => spaces.find(s => s.id === perm.space_id))
                                                .filter((s): s is Space => s !== undefined)
                                            
                                            return (
                                                <div
                                                    key={tableKey}
                                                    className={cn(
                                                        "p-3 rounded-lg border cursor-pointer transition-all",
                                                        "bg-white dark:bg-gray-800",
                                                        "border-gray-200 dark:border-gray-700",
                                                        isSelected 
                                                            ? "border-blue-500 bg-blue-50 dark:bg-blue-900/20" 
                                                            : "hover:border-blue-300 dark:hover:border-blue-600"
                                                    )}
                                                    onClick={() => {
                                                        if (isSelected) {
                                                            setSelectedTables(selectedTables.filter(t => t !== tableKey))
                                                        } else {
                                                            setSelectedTables([...selectedTables, tableKey])
                                                        }
                                                    }}
                                                >
                                                    <div className="flex items-center gap-3">
                                                        <input
                                                            type="checkbox"
                                                            checked={isSelected}
                                                            onChange={() => {
                                                                if (isSelected) {
                                                                    setSelectedTables(selectedTables.filter(t => t !== tableKey))
                                                                } else {
                                                                    setSelectedTables([...selectedTables, tableKey])
                                                                }
                                                            }}
                                                            className="w-4 h-4 text-blue-600 rounded"
                                                            onClick={(e) => e.stopPropagation()}
                                                        />
                                                        <div className="flex-1">
                                                            <div className="flex items-center gap-2">
                                                                <h4 className="text-sm font-medium text-foreground">
                                                                    {table.name}
                                                                </h4>
                                                                {spacesWithThisTable.length > 0 && (
                                                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400">
                                                                        In {spacesWithThisTable.length} space{spacesWithThisTable.length !== 1 ? 's' : ''}
                                                                    </span>
                                                                )}
                                                            </div>
                                                            <p className="text-xs text-muted-foreground">
                                                                {table.schema || 'public'}
                                                                 {table.rowCount !== null && table.rowCount !== undefined && (
                                                                    <> • {table.rowCount.toLocaleString()} rows</>
                                                                )}
                                                            </p>
                                                            {spacesWithThisTable.length > 0 && (
                                                                <div className="mt-1 flex flex-wrap gap-1">
                                                                    {spacesWithThisTable.map(space => (
                                                                        <span
                                                                            key={space.id}
                                                                            className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-muted-foreground"
                                                                        >
                                                                            {space.name}
                                                                        </span>
                                                                    ))}
                                                                </div>
                                                            )}
                                                        </div>
                                                    </div>
                                                </div>
                                            )
                                        })}
                                    </div>
                                )
                            })()}
                        </div>
                        
                        {/* Coluna Direita - Space Selection e Tabelas Selecionadas */}
                        <div className="flex-1 overflow-y-auto p-5">
                                <div className="mb-4">
                                    <h3 className="text-sm font-semibold text-foreground mb-2">
                                        Assign to Space
                                    </h3>
                                    
                                    {/* Space Selector */}
                                    <div className="mb-4">
                                        <label className="text-xs font-medium text-foreground mb-2 block">
                                            Select Space
                                        </label>
                                        <div className="flex gap-2">
                                            <select
                                                value={selectedSpaceId}
                                                onChange={(e) => setSelectedSpaceId(e.target.value)}
                                                className={cn(
                                                    "flex-1 h-9 px-3 rounded-lg text-sm border",
                                                    isDark 
                                                        ? "bg-white/4 border-white/8 text-foreground" 
                                                        : "bg-white border-black/8 text-foreground",
                                                    "appearance-none cursor-pointer"
                                                )}
                                            >
                                                <option value="">Select a space...</option>
                                                {spaces.map(space => (
                                                    <option key={space.id} value={space.id}>
                                                        {space.name}
                                                    </option>
                                                ))}
                                            </select>
                                            <button
                                                onClick={() => setShowCreateSpaceModal(true)}
                                                className={cn(
                                                    "px-3 py-2 rounded-lg text-sm font-medium",
                                                    "bg-primary hover:bg-primary/90 text-primary-foreground",
                                                    "transition-colors flex items-center gap-2"
                                                )}
                                            >
                                                <Plus className="w-4 h-4" />
                                                New Space
                                            </button>
                                        </div>
                                    </div>
                                    
                                    {/* Tabelas já atribuídas ao space selecionado */}
                                    {selectedSpaceId && (() => {
                                        const selectedSpacePerm = spacePerms.find(p => p.space_id === selectedSpaceId)
                                        const existingTables = selectedSpacePerm?.table_access || []
                                        const selectedSpace = spaces.find(s => s.id === selectedSpaceId)
                                        
                                        return (
                                            <div className="mb-4">
                                                <div className="flex items-center justify-between mb-2">
                                                    <p className="text-xs font-medium text-foreground">
                                                        Tables in "{selectedSpace?.name}" ({existingTables.length})
                                                    </p>
                                                </div>
                                                {existingTables.length > 0 ? (
                                                    <div className="space-y-2 max-h-48 overflow-y-auto border rounded-lg p-2 bg-gray-50 dark:bg-gray-900/30">
                                                        {existingTables.map(tableName => {
                                                            // Encontrar a tabela completa para mostrar schema e outras info
                                                            const fullTable = tables.find(t => t.name === tableName)
                                                            const tableKey = fullTable ? `${fullTable.schema || 'public'}.${tableName}` : tableName
                                                            const isSelected = selectedTables.includes(tableKey)
                                                            
                                                            return (
                                                                <div
                                                                    key={tableName}
                                                                    className={cn(
                                                                        "p-2 rounded border text-xs",
                                                                        "bg-white dark:bg-gray-800",
                                                                        "border-gray-200 dark:border-gray-700",
                                                                        isSelected && "border-blue-500 bg-blue-50 dark:bg-blue-900/20"
                                                                    )}
                                                                >
                                                                    <div className="flex items-center justify-between">
                                                                        <div>
                                                                            <p className="font-medium text-foreground">{tableName}</p>
                                                                            {fullTable && (
                                                                                <p className="text-[10px] text-muted-foreground">
                                                                                    {fullTable.schema || 'public'}
{fullTable.rowCount !== null && fullTable.rowCount !== undefined && (
                                                                                        <> • {fullTable.rowCount.toLocaleString()} rows</>
                                                                                    )}
                                                                                </p>
                                                                            )}
                                                                        </div>
                                                                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400">
                                                                            Already assigned
                                                                        </span>
                                                                    </div>
                                                                </div>
                                                            )
                                                        })}
                                                    </div>
                                                ) : (
                                                    <div className="text-xs text-muted-foreground text-center py-4 border rounded-lg bg-gray-50 dark:bg-gray-900/30">
                                                        No tables assigned to this space yet
                                                    </div>
                                                )}
                                            </div>
                                        )
                                    })()}
                                    
                                    {/* Selected Tables Preview - Mostrar quais são novas vs já existentes */}
                                    {selectedTables.length > 0 && selectedSpaceId && (() => {
                                        const selectedSpacePerm = spacePerms.find(p => p.space_id === selectedSpaceId)
                                        const existingTables = selectedSpacePerm?.table_access || []
                                        
                                        // Separar tabelas novas das já existentes
                                        const newTables = selectedTables.filter(tableKey => {
                                            const tableName = tableKey.split('.')[1]
                                            return !existingTables.includes(tableName)
                                        })
                                        const alreadyAssignedTables = selectedTables.filter(tableKey => {
                                            const tableName = tableKey.split('.')[1]
                                            return existingTables.includes(tableName)
                                        })
                                        
                                        return (
                                            <div className="mb-4">
                                                <p className="text-xs font-medium text-foreground mb-2">
                                                    Selected Tables ({selectedTables.length})
                                                </p>
                                                
                                                {/* Novas tabelas (serão adicionadas) */}
                                                {newTables.length > 0 && (
                                                    <div className="mb-3">
                                                        <p className="text-[10px] font-medium text-green-600 dark:text-green-400 mb-1">
                                                            New ({newTables.length})
                                                        </p>
                                                        <div className="space-y-2 max-h-32 overflow-y-auto">
                                                            {newTables.map(tableKey => {
                                                                const [schema, name] = tableKey.split('.')
                                                                return (
                                                                    <div
                                                                        key={tableKey}
                                                                        className={cn(
                                                                            "p-2 rounded border",
                                                                            "bg-green-50 dark:bg-green-900/20",
                                                                            "border-green-200 dark:border-green-800"
                                                                        )}
                                                                    >
                                                                        <div className="flex items-center justify-between">
                                                                            <div>
                                                                                <p className="text-xs font-medium text-foreground">{name}</p>
                                                                                <p className="text-[10px] text-muted-foreground">{schema}</p>
                                                                            </div>
                                                                            <button
                                                                                onClick={() => {
                                                                                    setSelectedTables(selectedTables.filter(t => t !== tableKey))
                                                                                }}
                                                                                className="text-red-500 hover:text-red-700"
                                                                            >
                                                                                <X className="w-3 h-3" />
                                                                            </button>
                                                                        </div>
                                                                    </div>
                                                                )
                                                            })}
                                                        </div>
                                                    </div>
                                                )}
                                                
                                                {/* Tabelas já atribuídas (serão ignoradas) */}
                                                {alreadyAssignedTables.length > 0 && (
                                                    <div className="mb-3">
                                                        <p className="text-[10px] font-medium text-orange-600 dark:text-orange-400 mb-1">
                                                            Already Assigned ({alreadyAssignedTables.length}) - Will be skipped
                                                        </p>
                                                        <div className="space-y-2 max-h-32 overflow-y-auto">
                                                            {alreadyAssignedTables.map(tableKey => {
                                                                const [schema, name] = tableKey.split('.')
                                                                return (
                                                                    <div
                                                                        key={tableKey}
                                                                        className={cn(
                                                                            "p-2 rounded border",
                                                                            "bg-orange-50 dark:bg-orange-900/20",
                                                                            "border-orange-200 dark:border-orange-800"
                                                                        )}
                                                                    >
                                                                        <div className="flex items-center justify-between">
                                                                            <div>
                                                                                <p className="text-xs font-medium text-foreground">{name}</p>
                                                                                <p className="text-[10px] text-muted-foreground">{schema}</p>
                                                                            </div>
                                                                            <button
                                                                                onClick={() => {
                                                                                    setSelectedTables(selectedTables.filter(t => t !== tableKey))
                                                                                }}
                                                                                className="text-red-500 hover:text-red-700"
                                                                            >
                                                                                <X className="w-3 h-3" />
                                                                            </button>
                                                                        </div>
                                                                    </div>
                                                                )
                                                            })}
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        )
                                    })()}
                                    
                                    {/* Assign Button - Só atribuir novas tabelas */}
                                    {selectedSpaceId && selectedTables.length > 0 && (() => {
                                        const selectedSpacePerm = spacePerms.find(p => p.space_id === selectedSpaceId)
                                        const existingTables = selectedSpacePerm?.table_access || []
                                        const newTables = selectedTables.filter(tableKey => {
                                            const tableName = tableKey.split('.')[1]
                                            return !existingTables.includes(tableName)
                                        })
                                        
                                        return newTables.length > 0 ? (
                                            <button
                                                onClick={async () => {
                                                    try {
                                                        // Se já existe permissão, atualizar com novas tabelas
                                                        if (selectedSpacePerm) {
                                                            const currentTables = selectedSpacePerm.table_access || []
                                                            const newTableNames = newTables.map(t => t.split('.')[1])
                                                            const updatedTables = [...new Set([...currentTables, ...newTableNames])]
                                                            
                                                            await permissionsApi.updatePermission(selectedSpacePerm.id, {
                                                                access_level: 'custom',
                                                                table_access: updatedTables
                                                            })
                                                        } else {
                                                            // Criar nova permissão
                                                            await handleAssignToSpace(
                                                                conn.id,
                                                                selectedSpaceId,
                                                                'custom',
                                                                newTables.map(t => t.split('.')[1])
                                                            )
                                                        }
                                                        
                                                        // Reload permissions
                                                        await loadPermissions(conn.id)
                                                        // NÃO limpar seleções - permitir continuar trabalhando
                                                        // setSelectedTables([])
                                                        // setSelectedSpaceId('')
                                                    } catch (error) {
                                                        console.error('Error assigning tables:', error)
                                                        alert(`Error assigning tables: ${error instanceof Error ? error.message : 'Unknown error'}`)
                                                    }
                                                }}
                                                className={cn(
                                                    "w-full px-4 py-2 rounded-lg text-sm font-medium mb-4",
                                                    "bg-primary hover:bg-primary/90 text-primary-foreground",
                                                    "transition-colors"
                                                )}
                                            >
                                                Add {newTables.length} New Table{newTables.length !== 1 ? 's' : ''} to Space
                                            </button>
                                        ) : null
                                    })()}
                                    
                                    {/* Existing Permissions - Lista de todos os spaces com permissões */}
                                    {spacePerms.length > 0 && (
                                        <div className="mt-6">
                                            <h4 className="text-xs font-semibold text-foreground mb-3">
                                                All Space Permissions
                                            </h4>
                                            <div className="space-y-2">
                                                {spacePerms.map(perm => {
                                                    const space = spaces.find(s => s.id === perm.space_id)
                                                    if (!space) return null
                                                    const isSelected = perm.space_id === selectedSpaceId
                                                    
                                                    return (
                                                        <div
                                                            key={perm.id}
                                                            className={cn(
                                                                "p-3 rounded-lg border cursor-pointer transition-all",
                                                                "bg-white dark:bg-gray-800",
                                                                "border-gray-200 dark:border-gray-700",
                                                                isSelected && "border-blue-500 bg-blue-50 dark:bg-blue-900/20"
                                                            )}
                                                            onClick={() => perm.space_id && setSelectedSpaceId(perm.space_id)}
                                                        >
                                                            <div className="flex items-center justify-between">
                                                                <div className="flex-1">
                                                                    <div className="flex items-center gap-2">
                                                                        <p className="text-sm font-medium text-foreground">{space.name}</p>
                                                                        {isSelected && (
                                                                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400">
                                                                                Selected
                                                                            </span>
                                                                        )}
                                                                    </div>
                                                                    <p className="text-xs text-muted-foreground mt-1">
                                                                        {perm.table_access?.length || 0} tables • {perm.access_level}
                                                                    </p>
                                                                    {perm.table_access && perm.table_access.length > 0 && (
                                                                        <div className="mt-2 flex flex-wrap gap-1">
                                                                            {perm.table_access.slice(0, 5).map(tableName => (
                                                                                <span
                                                                                    key={tableName}
                                                                                    className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-muted-foreground"
                                                                                >
                                                                                    {tableName}
                                                                                </span>
                                                                            ))}
                                                                            {perm.table_access.length > 5 && (
                                                                                <span className="text-[10px] text-muted-foreground">
                                                                                    +{perm.table_access.length - 5} more
                                                                                </span>
                                                                            )}
                                                                        </div>
                                                                    )}
                                                                </div>
                                                                <button
                                                                    onClick={(e) => {
                                                                        e.stopPropagation()
                                                                        removePermission(perm.id)
                                                                    }}
                                                                    className="text-red-500 hover:text-red-700 ml-2"
                                                                >
                                                                    <Trash2 className="w-4 h-4" />
                                                                </button>
                                                            </div>
                                                        </div>
                                                    )
                                                })}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}
                    
                    
                    {connectionDashboardTab === 'settings' && (
                        <div className="p-5">
                            {/* Form de edição - código existente */}
                            {(() => {
                                const connector = selectedConnector || getConnectorById(conn.connectorId)
                                if (!connector) return <div>Connector not found</div>
                                
                                const currentAuthMethod = connector.authMethods.find(m => m.type === selectedAuthMethod)
                                const isFormValid = () => {
                                    if (!connector) return false
                                    const allFields = [...connector.fields, ...(currentAuthMethod?.fields || [])]
                                    return allFields.every(field => !field.required || (formData[field.key] !== undefined && formData[field.key] !== ''))
                                }
                                
                                return (
                                    <div className="max-w-3xl mx-auto space-y-6">
                                        {/* Connection Name */}
                                        <div>
                                            <label className="text-sm font-medium text-foreground mb-2 block">
                                                Connection Name <span className="text-red-500">*</span>
                                            </label>
                                            <Input
                                                value={formData.name || ''}
                                                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                                placeholder={`e.g., Production ${connector.name}`}
                                                className={cn(
                                                    "h-10 text-sm",
                                                    isDark 
                                                        ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                                        : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                                                )}
                                            />
                                        </div>
                                        
                                        {/* Connector Fields */}
                                        <div className="space-y-4 border-t pt-6">
                                            <h4 className="text-sm font-semibold text-foreground mb-4">Connection Details</h4>
                                            <div className="grid grid-cols-2 gap-4">
                                                {connector.fields.map(field => (
                                                    <DynamicFormField
                                                        key={field.key}
                                                        field={field}
                                                        value={formData[field.key]}
                                                        onChange={(value) => setFormData({ ...formData, [field.key]: value })}
                                                        isDark={isDark}
                                                    />
                                                ))}
                                            </div>
                                        </div>
                                        
                                        {/* Authentication */}
                                        {connector.authMethods.length > 0 && (
                                            <div className="space-y-4 border-t pt-6">
                                                <h4 className="text-sm font-semibold text-foreground mb-4">Authentication</h4>
                                                <div className="space-y-4">
                                                    <div>
                                                        <label className="text-sm font-medium text-foreground mb-2 block">
                                                            Authentication Method <span className="text-red-500">*</span>
                                                        </label>
                                                        <div className="relative">
                                                            <select
                                                                value={selectedAuthMethod}
                                                                onChange={(e) => setSelectedAuthMethod(e.target.value)}
                                                                className={cn(
                                                                    "h-10 px-3 pr-8 rounded-lg text-sm border w-full",
                                                                    isDark 
                                                                        ? "bg-white/4 border-white/8 text-foreground" 
                                                                        : "bg-white border-black/8 text-foreground",
                                                                    "appearance-none cursor-pointer"
                                                                )}
                                                            >
                                                                {connector.authMethods.map(method => (
                                                                    <option key={method.type} value={method.type}>{method.label}</option>
                                                                ))}
                                                            </select>
                                                            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                                                        </div>
                                                        {currentAuthMethod && currentAuthMethod.instructions && (
                                                            <p className="text-xs text-muted-foreground mt-1">{currentAuthMethod.instructions}</p>
                                                        )}
                                                    </div>
                                                    {currentAuthMethod && currentAuthMethod.fields.map(field => (
                                                        <DynamicFormField
                                                            key={field.key}
                                                            field={field}
                                                            value={formData[field.key]}
                                                            onChange={(value) => setFormData({ ...formData, [field.key]: value })}
                                                            isDark={isDark}
                                                        />
                                                    ))}
                                                </div>
                                            </div>
                                        )}
                                        
                                        {/* Description */}
                                        <div>
                                            <label className="text-sm font-medium text-foreground mb-2 block">
                                                Description
                                            </label>
                                            <textarea
                                                value={formData.description || ''}
                                                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                                                placeholder="Optional description for this connection"
                                                rows={3}
                                                className={cn(
                                                    "w-full rounded-lg text-sm p-3 resize-none",
                                                    isDark 
                                                        ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                                        : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                                                )}
                                            />
                                        </div>
                                        
                                        {/* Test Result */}
                                        {testResult && (
                                            <div className={cn(
                                                "p-4 rounded-lg border",
                                                testResult.success
                                                    ? "bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800"
                                                    : "bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800"
                                            )}>
                                                <div className="flex items-center gap-2">
                                                    {testResult.success ? (
                                                        <CheckCircle2 className="w-5 h-5 text-green-600 dark:text-green-400" />
                                                    ) : (
                                                        <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
                                                    )}
                                                    <p className={cn(
                                                        "text-sm font-medium",
                                                        testResult.success ? "text-green-700 dark:text-green-300" : "text-red-700 dark:text-red-300"
                                                    )}>
                                                        {testResult.message}
                                                    </p>
                                                </div>
                                            </div>
                                        )}
                                        
                                        {/* Actions */}
                                        <div className="flex gap-3 pt-4 border-t">
                                            <button
                                                onClick={handleTestConnection}
                                                disabled={!isFormValid() || testingConnection !== null}
                                                className={cn(
                                                    "px-4 py-2 rounded-lg text-sm font-medium",
                                                    "bg-gray-500 hover:bg-gray-600 text-white",
                                                    "disabled:opacity-50 disabled:cursor-not-allowed",
                                                    "transition-colors flex items-center gap-2"
                                                )}
                                            >
                                                {testingConnection && <RefreshCw className="w-4 h-4 animate-spin" />}
                                                {testingConnection ? 'Testing...' : 'Test Connection'}
                                            </button>
                                            <button
                                                onClick={() => {
                                                    if (editingConnection) {
                                                        handleSyncTables(editingConnection)
                                                    }
                                                }}
                                                disabled={syncingConnection !== null || !testResult?.success}
                                                className={cn(
                                                    "px-4 py-2 rounded-lg text-sm font-medium",
                                                    "bg-primary hover:bg-primary/90 text-primary-foreground",
                                                    "disabled:opacity-50 disabled:cursor-not-allowed",
                                                    "transition-colors flex items-center gap-2"
                                                )}
                                            >
                                                {syncingConnection === editingConnection ? (
                                                    <>
                                                        <RefreshCw className="w-4 h-4 animate-spin" />
                                                        Discovering Tables...
                                                    </>
                                                ) : (
                                                    <>
                                                        <Table className="w-4 h-4" />
                                                        Sync Tables
                                                    </>
                                                )}
                                            </button>
                                            <button
                                                onClick={handleSaveConnection}
                                                disabled={!isFormValid()}
                                                className={cn(
                                                    "px-4 py-2 rounded-lg text-sm font-medium ml-auto",
                                                    "bg-blue-500 hover:bg-blue-600 text-white",
                                                    "disabled:opacity-50 disabled:cursor-not-allowed",
                                                    "transition-colors"
                                                )}
                                            >
                                                Save Changes
                                            </button>
                                        </div>
                                    </div>
                                )
                            })()}
                        </div>
                    )}
                </div>
                
                {/* Add Permission Modal */}
                {showAddPermissionModal && editingConnection && (
                    <AddPermissionModal
                        isOpen={showAddPermissionModal}
                        onClose={() => setShowAddPermissionModal(false)}
                        connectionId={editingConnection}
                        type={addPermissionType}
                        spaces={spaces}
                        crews={crews}
                        spaceCrews={spaceCrews}
                        connection={conn}
                        onAdd={addPermission}
                        isDark={isDark}
                    />
                )}
                
                {/* Create Space Modal */}
                {showCreateSpaceModal && (
                    <AssignSpaceModal
                        isOpen={showCreateSpaceModal}
                        onClose={() => {
                            setShowCreateSpaceModal(false)
                            // Refresh spaces after creating
                            fetchSpaces()
                        }}
                        connectionId={conn.id}
                        spaces={spaces}
                        connection={conn}
                        onCreateSpace={handleCreateSpace}
                        onAssign={async (connectionId, spaceId, accessLevel, selectedTables) => {
                            await handleAssignToSpace(connectionId, spaceId, accessLevel, selectedTables)
                            await loadPermissions(connectionId)
                            setShowCreateSpaceModal(false)
                            setSelectedSpaceId(spaceId)
                            setSelectedTables([])
                            fetchSpaces()
                        }}
                        onFinish={async () => {
                            // Refresh permissions after assigning
                            await loadPermissions(conn.id)
                        }}
                        isDark={isDark}
                    />
                )}
            </div>
        )
    }
    
    // Render connection form view (for new connections)
    if (viewMode === 'detail' && !editingConnection && selectedConnector) {
        const currentAuthMethod = selectedConnector.authMethods.find(m => m.type === selectedAuthMethod)
        const isFormValid = () => {
            if (!selectedConnector) return false
            const allFields = [...selectedConnector.fields, ...(currentAuthMethod?.fields || [])]
            return allFields.every(field => !field.required || (formData[field.key] !== undefined && formData[field.key] !== ''))
        }
        
        return (
            <div className="h-full flex flex-col">
                {/* Header with Back Button */}
                <div className={cn(
                    "px-5 py-4 border-b",
                    isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
                )}>
                    <div className="flex items-center gap-3 mb-4">
                        <button
                            onClick={handleCancelEdit}
                            className={cn(
                                "p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-white/5 transition-colors"
                            )}
                        >
                            <ChevronLeft className="w-4 h-4" />
                        </button>
                        <div>
                            <h2 className="text-lg font-semibold text-foreground">
                                New Connection
                            </h2>
                            <p className="text-xs text-muted-foreground">
                                {selectedConnector.name} - {selectedConnector.description}
                            </p>
                        </div>
                    </div>
                </div>
                
                {/* Form Content */}
                <div className="flex-1 overflow-y-auto p-5">
                    <div className="max-w-3xl mx-auto space-y-6">
                        {/* Connection Name */}
                        <div>
                            <label className="text-sm font-medium text-foreground mb-2 block">
                                Connection Name <span className="text-red-500">*</span>
                            </label>
                            <Input
                                value={formData.name || ''}
                                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                placeholder={`e.g., Production ${selectedConnector.name}`}
                                className={cn(
                                    "h-10 text-sm",
                                    isDark 
                                        ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                        : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                                )}
                            />
                        </div>
                        
                        {/* Connector Fields */}
                        <div className="space-y-4 border-t pt-6">
                            <h4 className="text-sm font-semibold text-foreground mb-4">Connection Details</h4>
                            <div className="grid grid-cols-2 gap-4">
                                {selectedConnector.fields.map(field => (
                                    <DynamicFormField
                                        key={field.key}
                                        field={field}
                                        value={formData[field.key]}
                                        onChange={(value) => setFormData({ ...formData, [field.key]: value })}
                                        isDark={isDark}
                                    />
                                ))}
                            </div>
                        </div>
                        
                        {/* Authentication */}
                        {selectedConnector.authMethods.length > 0 && (
                            <div className="space-y-4 border-t pt-6">
                                <h4 className="text-sm font-semibold text-foreground mb-4">Authentication</h4>
                                <div className="space-y-4">
                                    <div>
                                        <label className="text-sm font-medium text-foreground mb-2 block">
                                            Authentication Method <span className="text-red-500">*</span>
                                        </label>
                                        <div className="relative">
                                            <select
                                                value={selectedAuthMethod}
                                                onChange={(e) => setSelectedAuthMethod(e.target.value)}
                                                className={cn(
                                                    "h-10 px-3 pr-8 rounded-lg text-sm border w-full",
                                                    isDark 
                                                        ? "bg-white/4 border-white/8 text-foreground" 
                                                        : "bg-white border-black/8 text-foreground",
                                                    "appearance-none cursor-pointer"
                                                )}
                                            >
                                                {selectedConnector.authMethods.map(method => (
                                                    <option key={method.type} value={method.type}>{method.label}</option>
                                                ))}
                                            </select>
                                            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                                        </div>
                                        {currentAuthMethod && currentAuthMethod.instructions && (
                                            <p className="text-xs text-muted-foreground mt-1">{currentAuthMethod.instructions}</p>
                                        )}
                                    </div>
                                    {currentAuthMethod && currentAuthMethod.fields.map(field => (
                                        <DynamicFormField
                                            key={field.key}
                                            field={field}
                                            value={formData[field.key]}
                                            onChange={(value) => setFormData({ ...formData, [field.key]: value })}
                                            isDark={isDark}
                                        />
                                    ))}
                                </div>
                            </div>
                        )}
                        
                        {/* Description */}
                        <div>
                            <label className="text-sm font-medium text-foreground mb-2 block">
                                Description
                            </label>
                            <textarea
                                value={formData.description || ''}
                                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                                placeholder="Optional description for this connection"
                                rows={3}
                                className={cn(
                                    "w-full rounded-lg text-sm p-3 resize-none",
                                    isDark 
                                        ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                        : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                                )}
                            />
                        </div>
                        
                        {/* Test Result */}
                        {testResult && (
                            <div className={cn(
                                "p-4 rounded-lg border",
                                testResult.success
                                    ? "bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800"
                                    : "bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800"
                            )}>
                                <div className="flex items-center gap-2">
                                    {testResult.success ? (
                                        <CheckCircle2 className="w-5 h-5 text-green-600 dark:text-green-400" />
                                    ) : (
                                        <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
                                    )}
                                    <p className={cn(
                                        "text-sm font-medium",
                                        testResult.success ? "text-green-700 dark:text-green-300" : "text-red-700 dark:text-red-300"
                                    )}>
                                        {testResult.message}
                                    </p>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
                
                {/* Actions */}
                <div className={cn(
                    "px-5 py-4 border-t",
                    isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
                )}>
                    <div className="max-w-3xl mx-auto flex items-center justify-end gap-3">
                        <button
                            onClick={handleCancelEdit}
                            className={cn(
                                "px-4 py-2 rounded-lg text-sm font-medium",
                                "hover:bg-gray-100 dark:hover:bg-gray-700",
                                "transition-colors"
                            )}
                        >
                            Cancel
                        </button>
                        <button
                            onClick={handleTestConnection}
                            disabled={!isFormValid() || testingConnection !== null}
                            className={cn(
                                "px-4 py-2 rounded-lg text-sm font-medium",
                                "bg-gray-500 hover:bg-gray-600 text-white",
                                "disabled:opacity-50 disabled:cursor-not-allowed",
                                "transition-colors flex items-center gap-2"
                            )}
                        >
                            {testingConnection && <RefreshCw className="w-4 h-4 animate-spin" />}
                            {testingConnection ? 'Testing...' : 'Test Connection'}
                        </button>
                        <button
                            onClick={() => {
                                if (editingConnection) {
                                    handleSyncTables(editingConnection)
                                }
                            }}
                            disabled={syncingConnection !== null || !testResult?.success}
                            className={cn(
                                "px-4 py-2 rounded-lg text-sm font-medium",
                                "bg-primary hover:bg-primary/90 text-primary-foreground",
                                "disabled:opacity-50 disabled:cursor-not-allowed",
                                "transition-colors flex items-center gap-2"
                            )}
                        >
                            {syncingConnection === editingConnection ? (
                                <>
                                    <RefreshCw className="w-4 h-4 animate-spin" />
                                    Discovering Tables...
                                </>
                            ) : (
                                <>
                                    <Table className="w-4 h-4" />
                                    Sync Tables
                                </>
                            )}
                        </button>
                    </div>
                </div>
            </div>
        )
    }
    
    return (
        <div className="h-full flex flex-col">
            {/* Header Section */}
            <div className={cn(
                "px-5 py-4 border-b",
                isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
            )}>
                <div className="flex items-start justify-between mb-4">
                    <p className="text-xs text-muted-foreground flex-1">
                        Connect your data sources. Manage databases, documents, and APIs in one place.
                    </p>
                    <button
                        onClick={() => {
                            setViewMode('add')
                            setAddConnectionStep(1)
                            setSelectedConnectionType(null)
                            setSelectedConnectorForAdd(null)
                            setFormData({ name: '', description: '' })
                        }}
                        className={cn(
                            "px-4 py-2 rounded-lg text-sm font-medium",
                            "bg-primary hover:bg-primary/90 text-primary-foreground",
                            "flex items-center gap-2 transition-colors"
                        )}
                    >
                        <Plus className="w-4 h-4" />
                        Add Connection
                    </button>
                </div>
                
                {/* Stats Cards */}
                <div className="grid grid-cols-3 gap-4 mb-4">
                    <div className={cn(
                        "p-4 rounded-lg border",
                        "bg-white dark:bg-gray-800",
                        "border-gray-200 dark:border-gray-700"
                    )}>
                        <p className="text-xs text-muted-foreground mb-1">Total connections</p>
                        <p className="text-2xl font-semibold text-foreground">{stats.total}</p>
                    </div>
                    <div className={cn(
                        "p-4 rounded-lg border",
                        "bg-white dark:bg-gray-800",
                        "border-gray-200 dark:border-gray-700"
                    )}>
                        <p className="text-xs text-muted-foreground mb-1">Active connections</p>
                        <p className="text-2xl font-semibold text-foreground">{stats.active}</p>
                    </div>
                    <div className={cn(
                        "p-4 rounded-lg border",
                        "bg-white dark:bg-gray-800",
                        "border-gray-200 dark:border-gray-700"
                    )}>
                        <p className="text-xs text-muted-foreground mb-1">Inactive connections</p>
                        <p className="text-2xl font-semibold text-foreground">{stats.inactive}</p>
                    </div>
                </div>
                
                {/* Search and Filters */}
                <div className="flex items-center gap-3 flex-wrap">
                    <div className="relative flex-1">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/50" />
                        <Input
                            type="text"
                            placeholder="Search connections..."
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
                    <div className="relative">
                        <select
                            value={filterCategory}
                            onChange={(e) => {
                                setFilterCategory(e.target.value)
                                setCurrentPage(1)
                            }}
                            className={cn(
                                "h-9 px-3 pr-8 rounded-lg text-xs border",
                                isDark 
                                    ? "bg-white/4 border-white/8 text-foreground" 
                                    : "bg-white border-black/8 text-foreground",
                                "appearance-none cursor-pointer"
                            )}
                        >
                            <option value="all">All Categories</option>
                            {uniqueCategories.map(cat => (
                                <option key={cat} value={cat}>{cat.charAt(0).toUpperCase() + cat.slice(1)}</option>
                            ))}
                        </select>
                        <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                    </div>
                    <div className="relative">
                        <select
                            value={filterStatus}
                            onChange={(e) => {
                                setFilterStatus(e.target.value)
                                setCurrentPage(1)
                            }}
                            className={cn(
                                "h-9 px-3 pr-8 rounded-lg text-xs border",
                                isDark 
                                    ? "bg-white/4 border-white/8 text-foreground" 
                                    : "bg-white border-black/8 text-foreground",
                                "appearance-none cursor-pointer"
                            )}
                        >
                            <option value="all">All Status</option>
                            <option value="active">Active</option>
                            <option value="inactive">Inactive</option>
                        </select>
                        <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                    </div>
                    <div className="relative">
                        <select
                            value={filterSpace}
                            onChange={(e) => {
                                setFilterSpace(e.target.value)
                                setCurrentPage(1)
                            }}
                            className={cn(
                                "h-9 px-3 pr-8 rounded-lg text-xs border",
                                isDark 
                                    ? "bg-white/4 border-white/8 text-foreground" 
                                    : "bg-white border-black/8 text-foreground",
                                "appearance-none cursor-pointer"
                            )}
                        >
                            <option value="all">All Spaces</option>
                            {spaces.map(space => (
                                <option key={space.id} value={space.id}>{space.name}</option>
                            ))}
                        </select>
                        <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                    </div>
                    <div className="relative">
                        <select
                            value={filterCrew}
                            onChange={(e) => {
                                setFilterCrew(e.target.value)
                                setCurrentPage(1)
                            }}
                            className={cn(
                                "h-9 px-3 pr-8 rounded-lg text-xs border",
                                isDark 
                                    ? "bg-white/4 border-white/8 text-foreground" 
                                    : "bg-white border-black/8 text-foreground",
                                "appearance-none cursor-pointer"
                            )}
                        >
                            <option value="all">All Crews</option>
                            {crews.map(crew => (
                                <option key={crew.id} value={crew.id}>{crew.name}</option>
                            ))}
                        </select>
                        <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                    </div>
                    <button className={cn(
                        "h-9 w-9 rounded-lg flex items-center justify-center",
                        "hover:bg-gray-100 dark:hover:bg-white/5 transition-colors",
                        "border border-gray-200 dark:border-gray-700"
                    )}>
                        <RefreshCw className="w-4 h-4 text-muted-foreground" />
                    </button>
                </div>
            </div>

            {/* Content Area */}
            <div className="flex-1 overflow-y-auto p-5">
                {/* Loading State */}
                {isLoading && connections.length === 0 && (
                    <div className="flex items-center justify-center py-12">
                        <div className="text-center">
                            <RefreshCw className="w-8 h-8 animate-spin mx-auto text-blue-500 mb-2" />
                            <p className="text-sm text-muted-foreground">Loading connections...</p>
                        </div>
                    </div>
                )}
                
                {/* Error State */}
                {error && (
                    <div className="mb-4 p-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
                        <div className="flex items-center gap-2">
                            <AlertCircle className="w-5 h-5 text-red-500" />
                            <p className="text-sm text-red-700 dark:text-red-300">{error}</p>
                            <button
                                onClick={() => setError(null)}
                                className="ml-auto text-red-500 hover:text-red-700"
                            >
                                <X className="w-4 h-4" />
                            </button>
                        </div>
                    </div>
                )}
                
                {/* Empty State */}
                {!isLoading && connections.length === 0 && !error && (
                    <div className="flex flex-col items-center justify-center py-12">
                        <Database className="w-12 h-12 text-muted-foreground mb-4" />
                        <p className="text-sm text-muted-foreground mb-4">No connections found</p>
                        <button
                            onClick={() => setViewMode('add')}
                            className={cn(
                                "px-4 py-2 rounded-lg text-sm font-medium",
                                "bg-primary hover:bg-primary/90 text-primary-foreground",
                                "transition-colors"
                            )}
                        >
                            Add Connection
                        </button>
                    </div>
                )}
                
                {/* Connections List - Professional Grid */}
                {!isLoading && connections.length > 0 && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                        {paginatedConnections.map((conn) => {
                            const connector = getConnector(conn.connectorId)
                            if (!connector) return null
                            const Icon = connector.icon

                            // Get connection stats
                            const connPermissions = getConnectionPermissions(conn.id)
                            const connSpaces = connPermissions
                                .filter(p => p.space_id)
                                .map(p => spaces.find(s => s.id === p.space_id))
                                .filter(Boolean)
                            const connCrews = connPermissions
                                .filter(p => p.crew_id)
                                .map(p => crews.find(c => c.id === p.crew_id))
                                .filter(Boolean)
                            const tableCount = conn.metadata?.tables?.length || 0

                            // Unified blue color scheme for Data Catalog cards
                            const colorScheme = {
                                border: "border-blue-500/20",
                                gradient: "from-blue-500/10 via-blue-400/5 to-blue-600/10",
                                icon: "from-blue-500 to-blue-600",
                            }

                            return (
                                <div
                                    key={conn.id}
                                    onClick={() => {
                                        handleEditConnection(conn.id)
                                    }}
                                    className={cn(
                                        "group relative overflow-hidden cursor-pointer",
                                        "rounded-xl border transition-all duration-300",
                                        "bg-white/80 dark:bg-gray-800/80 backdrop-blur-sm",
                                        colorScheme.border,
                                        "hover:shadow-lg hover:shadow-blue-500/10 dark:hover:shadow-blue-500/20",
                                        "hover:scale-[1.02] hover:-translate-y-0.5"
                                    )}
                                >
                                    {/* Gradient background */}
                                    <div
                                        className={cn(
                                            "absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300",
                                            `bg-gradient-to-br ${colorScheme.gradient}`
                                        )}
                                    />

                                    <div className="relative p-4">
                                        <div className="flex items-start gap-3 mb-3">
                                            {/* Avatar with connector icon */}
                                            <div
                                                className={cn(
                                                    "flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center",
                                                    "bg-gradient-to-br shadow-lg",
                                                    colorScheme.icon,
                                                    "ring-2 ring-white/20 dark:ring-gray-700/50"
                                                )}
                                            >
                                                <Icon className="w-5 h-5 text-white" />
                                            </div>

                                            {/* Info */}
                                            <div className="flex-1 min-w-0 flex flex-col gap-1.5">
                                                <div className="flex items-center gap-2">
                                                    <h3 className="font-semibold text-sm text-foreground truncate group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
                                                        {conn.name}
                                                    </h3>
                                                </div>
                                                <div className="flex items-center gap-2">
                                                    <span className="text-[11px] text-muted-foreground truncate">
                                                        {connector.name}
                                                    </span>
                                                    <span
                                                        className={cn(
                                                            "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium",
                                                            conn.status === "active"
                                                                ? "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400"
                                                                : conn.status === "error"
                                                                ? "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400"
                                                                : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"
                                                        )}
                                                    >
                                                        {conn.status === "active" && (
                                                            <CheckCircle2 className="w-3 h-3" />
                                                        )}
                                                        {conn.status === "error" && (
                                                            <AlertCircle className="w-3 h-3" />
                                                        )}
                                                        {conn.status === "active"
                                                            ? "Active"
                                                            : conn.status === "error"
                                                            ? "Error"
                                                            : "Inactive"}
                                                    </span>
                                                </div>
                                            </div>
                                        </div>

                                        {/* Stats badges */}
                                        <TooltipProvider delayDuration={0}>
                                            <div className="flex items-center gap-1.5 flex-wrap">
                                                {/* Tables */}
                                                <Tooltip>
                                                    <TooltipTrigger asChild>
                                                        <div
                                                            className={cn(
                                                                "flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px]",
                                                                "bg-gray-100/80 dark:bg-gray-700/50",
                                                                "backdrop-blur-sm border border-gray-200/50 dark:border-gray-600/50"
                                                            )}
                                                            onClick={(e) => e.stopPropagation()}
                                                        >
                                                            <Table className="w-2.5 h-2.5 text-muted-foreground" />
                                                            <span className="font-medium text-foreground">
                                                                {tableCount}
                                                            </span>
                                                        </div>
                                                    </TooltipTrigger>
                                                    <TooltipContent side="top" className="text-xs">
                                                        Tabelas conectadas
                                                    </TooltipContent>
                                                </Tooltip>

                                                {/* Spaces */}
                                                <Tooltip>
                                                    <TooltipTrigger asChild>
                                                        <div
                                                            className={cn(
                                                                "flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px]",
                                                                "bg-gray-100/80 dark:bg-gray-700/50",
                                                                "backdrop-blur-sm border border-gray-200/50 dark:border-gray-600/50"
                                                            )}
                                                            onClick={(e) => e.stopPropagation()}
                                                        >
                                                            <Globe className="w-2.5 h-2.5 text-muted-foreground" />
                                                            <span className="font-medium text-foreground">
                                                                {connSpaces.length}
                                                            </span>
                                                        </div>
                                                    </TooltipTrigger>
                                                    <TooltipContent side="top" className="text-xs">
                                                        Spaces
                                                    </TooltipContent>
                                                </Tooltip>

                                                {/* Crews */}
                                                <Tooltip>
                                                    <TooltipTrigger asChild>
                                                        <div
                                                            className={cn(
                                                                "flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px]",
                                                                "bg-gray-100/80 dark:bg-gray-700/50",
                                                                "backdrop-blur-sm border border-gray-200/50 dark:border-gray-600/50"
                                                            )}
                                                            onClick={(e) => e.stopPropagation()}
                                                        >
                                                            <Users className="w-2.5 h-2.5 text-muted-foreground" />
                                                            <span className="font-medium text-foreground">
                                                                {connCrews.length}
                                                            </span>
                                                        </div>
                                                    </TooltipTrigger>
                                                    <TooltipContent side="top" className="text-xs">
                                                        Crews
                                                    </TooltipContent>
                                                </Tooltip>
                                            </div>
                                        </TooltipProvider>
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                )}
                
                {/* Pagination */}
                {totalPages > 1 && (
                    <div className="flex items-center justify-between mt-5">
                        <div className="text-xs text-muted-foreground">
                            {((currentPage - 1) * itemsPerPage) + 1} to {Math.min(currentPage * itemsPerPage, filteredConnections.length)} of {filteredConnections.length}
                        </div>
                        <div className="flex items-center gap-2">
                            <button
                                onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                                disabled={currentPage === 1}
                                className={cn(
                                    "px-3 py-1.5 rounded text-sm",
                                    "hover:bg-gray-100 dark:hover:bg-gray-700",
                                    "disabled:opacity-50 disabled:cursor-not-allowed",
                                    "transition-colors"
                                )}
                            >
                                <ChevronLeft className="w-4 h-4" />
                            </button>
                            <span className="text-xs text-muted-foreground">Previous</span>
                            <span className="text-xs text-muted-foreground">Next</span>
                            <button
                                onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                                disabled={currentPage === totalPages}
                                className={cn(
                                    "px-3 py-1.5 rounded text-sm",
                                    "hover:bg-gray-100 dark:hover:bg-gray-700",
                                    "disabled:opacity-50 disabled:cursor-not-allowed",
                                    "transition-colors"
                                )}
                            >
                                <ChevronRight className="w-4 h-4" />
                            </button>
                            <div className="relative ml-2">
                                <select
                                    value={itemsPerPage}
                                    onChange={(e) => {
                                        setItemsPerPage(Number(e.target.value))
                                        setCurrentPage(1)
                                    }}
                                    className={cn(
                                        "h-8 px-2 pr-6 rounded text-xs border",
                                        isDark 
                                            ? "bg-white/4 border-white/8 text-foreground" 
                                            : "bg-white border-black/8 text-foreground",
                                        "appearance-none cursor-pointer"
                                    )}
                                >
                                    <option value="10">10</option>
                                    <option value="12">12</option>
                                    <option value="20">20</option>
                                    <option value="40">40</option>
                                </select>
                                <ChevronDown className="absolute right-1 top-1/2 -translate-y-1/2 w-3 h-3 text-muted-foreground pointer-events-none" />
                            </div>
                        </div>
                    </div>
                )}
            </div>
            
            {/* Delete Confirmation Modal */}
            <DeleteConfirmationModal
                isOpen={deleteModalOpen}
                onClose={() => {
                    setDeleteModalOpen(false)
                    setItemToDelete(null)
                }}
                onConfirm={async () => {
                    if (itemToDelete) {
                        await deleteConnection(itemToDelete.id)
                    }
                }}
                itemName={itemToDelete?.name || ''}
                itemType="connection"
                isDark={isDark}
            />
        </div>
    )
}

// ============================================
// PERMISSIONS SECTION - Role-based by Module
// ============================================
const ROLES = [
    { id: 'admin', label: 'Admin', icon: Crown, color: 'purple', description: 'Full access to all features' },
    { id: 'commander', label: 'Commander', icon: Settings, color: 'blue', description: 'Can manage and configure' },
    { id: 'navigator', label: 'Navigator', icon: Navigation, color: 'green', description: 'Can navigate and organize' },
    { id: 'explorer', label: 'Explorer', icon: Compass, color: 'orange', description: 'Can explore and view' },
    { id: 'guest', label: 'Guest', icon: User, color: 'gray', description: 'Limited read-only access' },
]

const MODULES = ['Spaces', 'Crews']

export function PermissionsSection({ isDark }: { isDark: boolean }) {
    const [selectedCrew, setSelectedCrew] = useState<string | null>(null)
    
    // Load crews from API
    const [crews, setCrews] = useState<ApiCrew[]>([])
    
    useEffect(() => {
        const loadCrews = async () => {
            try {
                const apiCrews = await crewsApi.listCrews()
                setCrews(apiCrews)
            } catch (error) {
                console.error('Error loading crews:', error)
            }
        }
        loadCrews()
    }, [])
    
    // Permissions matrix: what each role can do within a crew
    const [rolePermissions, setRolePermissions] = useState<Record<string, Record<string, boolean>>>({
        commander: {
            createPlanets: true,
            viewPlanets: true,
            editPlanets: true,
            deletePlanets: true,
            sharePlanets: true,
            manageCrew: true,
            viewConnections: true,
            manageConnections: true,
        },
        navigator: {
            createPlanets: true,
            viewPlanets: true,
            editPlanets: true,
            deletePlanets: false,
            sharePlanets: true,
            manageCrew: false,
            viewConnections: true,
            manageConnections: false,
        },
        explorer: {
            createPlanets: false,
            viewPlanets: true,
            editPlanets: false,
            deletePlanets: false,
            sharePlanets: false,
            manageCrew: false,
            viewConnections: true,
            manageConnections: false,
        },
        guest: {
            createPlanets: false,
            viewPlanets: true,
            editPlanets: false,
            deletePlanets: false,
            sharePlanets: false,
            manageCrew: false,
            viewConnections: false,
            manageConnections: false,
        },
    })
    
    const permissionLabels: Record<string, string> = {
        createPlanets: 'Create Planets',
        viewPlanets: 'View Planets',
        editPlanets: 'Edit Planets',
        deletePlanets: 'Delete Planets',
        sharePlanets: 'Share Planets',
        manageCrew: 'Manage Crew',
        viewConnections: 'View Connections',
        manageConnections: 'Manage Connections',
    }
    
    const togglePermission = (role: string, permission: string) => {
        setRolePermissions(prev => ({
            ...prev,
            [role]: {
                ...prev[role],
                [permission]: !prev[role]?.[permission]
            }
        }))
    }

    const crewRoles = ROLES.filter(r => r.id !== 'admin') // Exclude admin from crew roles
    
    return (
        <div className="h-full flex flex-col">
            {/* Header */}
            <div className={cn(
                "px-5 py-4 border-b",
                isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
            )}>
                <div className="flex items-center justify-between mb-3">
                    <div className="flex-1">
                        <p className="text-xs text-muted-foreground mb-1">
                            Configure what each role can do within crews. These permissions apply to all crews across the platform.
                        </p>
                    </div>
                </div>
            </div>

            {/* Permissions Matrix */}
            <div className="flex-1 overflow-y-auto p-5">
                <div className={cn(
                    "rounded-lg border overflow-hidden",
                    "bg-white dark:bg-gray-800",
                    "border-gray-200 dark:border-gray-700"
                )}>
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead className={cn(
                                "border-b",
                                "bg-gray-50 dark:bg-gray-900/50",
                                "border-gray-200 dark:border-gray-700"
                            )}>
                                <tr>
                                    <th className="text-left px-4 py-3 text-xs font-semibold text-foreground">Permission</th>
                                    {crewRoles.map(role => {
                                        const Icon = role.icon
                                        const colorClasses = {
                                            blue: "bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400",
                                            green: "bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400",
                                            orange: "bg-orange-100 dark:bg-orange-900/30 text-orange-600 dark:text-orange-400",
                                            gray: "bg-gray-100 dark:bg-gray-900/30 text-gray-600 dark:text-gray-400",
                                        }
                                        return (
                                            <th key={role.id} className="text-center px-4 py-3">
                                                <div className="flex flex-col items-center gap-1">
                                                    <div className={cn(
                                                        "w-8 h-8 rounded-lg flex items-center justify-center",
                                                        colorClasses[role.color as keyof typeof colorClasses]
                                                    )}>
                                                        <Icon className="w-4 h-4" />
                                                    </div>
                                                    <span className="text-xs font-semibold text-foreground">{role.label}</span>
                                                </div>
                                            </th>
                                        )
                                    })}
                                </tr>
                            </thead>
                            <tbody>
                                {Object.entries(permissionLabels).map(([permissionKey, permissionLabel]) => (
                                    <tr
                                        key={permissionKey}
                                        className={cn(
                                            "border-b border-gray-200 dark:border-gray-700",
                                            "hover:bg-gray-50 dark:hover:bg-gray-900/30"
                                        )}
                                    >
                                        <td className="px-4 py-3">
                                            <span className="text-sm text-foreground">{permissionLabel}</span>
                                        </td>
                                        {crewRoles.map(role => (
                                            <td key={role.id} className="px-4 py-3 text-center">
                                                <button
                                                    onClick={() => togglePermission(role.id, permissionKey)}
                                                    className={cn(
                                                        "w-6 h-6 rounded border-2 flex items-center justify-center transition-all",
                                                        rolePermissions[role.id]?.[permissionKey]
                                                            ? "bg-blue-500 border-blue-500 text-white"
                                                            : "bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600 text-transparent"
                                                    )}
                                                >
                                                    {rolePermissions[role.id]?.[permissionKey] && (
                                                        <CheckCircle2 className="w-4 h-4" />
                                                    )}
                                                </button>
                                            </td>
                                        ))}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>

                {/* Role Descriptions */}
                <div className="mt-6 grid grid-cols-4 gap-4">
                    {crewRoles.map(role => {
                        const Icon = role.icon
                        const colorClasses = {
                            blue: "bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400",
                            green: "bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400",
                            orange: "bg-orange-100 dark:bg-orange-900/30 text-orange-600 dark:text-orange-400",
                            gray: "bg-gray-100 dark:bg-gray-900/30 text-gray-600 dark:text-gray-400",
                        }
                        return (
                            <div
                                key={role.id}
                                className={cn(
                                    "p-4 rounded-lg border",
                                    "bg-white dark:bg-gray-800",
                                    "border-gray-200 dark:border-gray-700"
                                )}
                            >
                                <div className={cn(
                                    "w-10 h-10 rounded-lg mx-auto mb-3 flex items-center justify-center",
                                    colorClasses[role.color as keyof typeof colorClasses]
                                )}>
                                    <Icon className="w-5 h-5" />
                                </div>
                                <h4 className="text-sm font-semibold text-foreground text-center mb-1">{role.label}</h4>
                                <p className="text-xs text-muted-foreground text-center">{role.description}</p>
                            </div>
                        )
                    })}
                </div>
            </div>
        </div>
    )
}

// ============================================
// SPACES & CREWS SECTION - Hierarchical Management
// ============================================
export function SpacesCrewsSection({ isDark }: { isDark: boolean }) {
    const [activeTab, setActiveTab] = useState<'spaces' | 'crews'>('spaces')
    const [spaces, setSpaces] = useState<Space[]>([])
    
    useEffect(() => {
        const loadSpaces = async () => {
            try {
                const apiSpaces = await spacesApi.listSpaces()
                setSpaces(apiSpaces)
            } catch (error) {
                console.error('Error loading spaces:', error)
            }
        }
        loadSpaces()
    }, [])
    
    const [crews, setCrews] = useState<ApiCrew[]>([])
    
    useEffect(() => {
        const loadCrews = async () => {
            try {
                const apiCrews = await crewsApi.listCrews()
                setCrews(apiCrews)
            } catch (error) {
                console.error('Error loading crews:', error)
            }
        }
        loadCrews()
    }, [])
    const [crewMembers, setCrewMembers] = useState<ApiCrewMember[]>([])
    const [users] = useState([
        { id: '1', name: 'Felipe Meneses', email: 'felipe.meneses@thedatafirst.com', avatar: 'F' },
        { id: '2', name: 'Kaique Mendonça', email: 'kaique.mendonca855@gmail.com', avatar: 'K' },
        { id: '3', name: 'Lucas Ventura', email: 'lucasventura.teamblue@gmail.com', avatar: 'L' },
    ])
    
    const [showAddSpaceModal, setShowAddSpaceModal] = useState(false)
    const [showAddCrewModal, setShowAddCrewModal] = useState(false)
    const [selectedSpace, setSelectedSpace] = useState<string | null>(null)
    const [selectedCrew, setSelectedCrew] = useState<string | null>(null)
    const [searchQuery, setSearchQuery] = useState('')
    const [spaceFormData, setSpaceFormData] = useState({ name: '', description: '', color: 'blue' })
    const [crewFormData, setCrewFormData] = useState({ name: '', description: '', spaceId: '' })

    const filteredSpaces = spaces.filter(space => 
        space.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        space.description?.toLowerCase().includes(searchQuery.toLowerCase())
    )

    const filteredCrews = crews.filter(crew => {
        const matchesSearch = crew.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                            crew.description?.toLowerCase().includes(searchQuery.toLowerCase())
        const matchesSpace = selectedSpace ? crew.space_id === selectedSpace : true
        return matchesSearch && matchesSpace
    })

    const handleAddSpace = async () => {
        try {
            const newSpace = await spacesApi.createSpace({
            name: spaceFormData.name,
                description: spaceFormData.description
            })
        setSpaces([...spaces, newSpace])
        setShowAddSpaceModal(false)
        setSpaceFormData({ name: '', description: '', color: 'blue' })
        } catch (error) {
            console.error('Error creating space:', error)
        }
    }

    const handleAddCrew = async () => {
        try {
            const newCrew = await crewsApi.createCrew({
            name: crewFormData.name,
            description: crewFormData.description,
                space_id: crewFormData.spaceId
            })
        setCrews([...crews, newCrew])
        setShowAddCrewModal(false)
        setCrewFormData({ name: '', description: '', spaceId: '' })
        } catch (error) {
            console.error('Error creating crew:', error)
        }
    }

    const deleteSpace = (id: string) => {
        // Remove crews in this space
        const spaceCrews = crews.filter(c => c.space_id === id)
        setCrews(crews.filter(c => c.space_id !== id))
        // Remove crew members
        setCrewMembers(crewMembers.filter(cm => !spaceCrews.some(sc => sc.id === cm.crew_id)))
        setSpaces(spaces.filter(s => s.id !== id))
    }

    const deleteCrew = async (id: string) => {
        try {
            await crewsApi.deleteCrew(id)
        setCrews(crews.filter(c => c.id !== id))
            // Reload crew members if needed
            setCrewMembers(crewMembers.filter(cm => cm.crew_id !== id))
        } catch (error) {
            console.error('Error deleting crew:', error)
        }
    }

    const getCrewMembers = (crewId: string) => {
        return crewMembers
            .filter(cm => cm.crew_id === crewId)
            .map(cm => {
                const user = users.find(u => u.id === cm.user_id)
                return { ...cm, user }
            })
    }

    const getSpaceStats = (spaceId: string) => {
        const spaceCrews = crews.filter(c => c.space_id === spaceId)
        const spaceMembers = new Set(
            spaceCrews.flatMap(c => crewMembers.filter(cm => cm.crew_id === c.id).map(cm => cm.user_id))
        )
        return {
            crews: spaceCrews.length,
            members: spaceMembers.size,
            connections: 0 // Connections count would need to be loaded separately
        }
    }

    const colorOptions = [
        { value: 'blue', label: 'Blue', class: 'bg-blue-500' },
        { value: 'purple', label: 'Purple', class: 'bg-purple-500' },
        { value: 'green', label: 'Green', class: 'bg-green-500' },
        { value: 'orange', label: 'Orange', class: 'bg-orange-500' },
        { value: 'red', label: 'Red', class: 'bg-red-500' },
        { value: 'pink', label: 'Pink', class: 'bg-pink-500' },
    ]

    return (
        <div className="h-full flex flex-col">
            {/* Header */}
            <div className={cn(
                "px-5 py-4 border-b",
                isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
            )}>
                <div className="flex items-center justify-between mb-3">
                    <div className="flex-1">
                        <p className="text-xs text-muted-foreground mb-1">
                            Organize your teams into Spaces and Crews. Spaces contain multiple Crews, and Crews contain team members with specific roles.
                        </p>
                    </div>
                </div>

                {/* Tabs */}
                <div className="flex gap-2 border-b border-gray-200 dark:border-gray-700">
                    <button
                        onClick={() => setActiveTab('spaces')}
                        className={cn(
                            "px-4 py-2 text-sm font-medium border-b-2 transition-colors",
                            activeTab === 'spaces'
                                ? "border-blue-500 text-blue-600 dark:text-blue-400"
                                : "border-transparent text-muted-foreground hover:text-foreground"
                        )}
                    >
                        Spaces ({spaces.length})
                    </button>
                    <button
                        onClick={() => setActiveTab('crews')}
                        className={cn(
                            "px-4 py-2 text-sm font-medium border-b-2 transition-colors",
                            activeTab === 'crews'
                                ? "border-blue-500 text-blue-600 dark:text-blue-400"
                                : "border-transparent text-muted-foreground hover:text-foreground"
                        )}
                    >
                        Crews ({crews.length})
                    </button>
                </div>

                {/* Search */}
                <div className="mt-3">
                    <div className="relative flex-1">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/50" />
                        <Input
                            type="text"
                            placeholder={activeTab === 'spaces' ? "Search spaces..." : "Search crews..."}
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
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-5">
                {activeTab === 'spaces' ? (
                    <div className="space-y-4">
                        {/* Add Space Button */}
                        <button
                            onClick={() => setShowAddSpaceModal(true)}
                            className={cn(
                                "w-full p-4 rounded-xl border-2 border-dashed",
                                "border-primary/40 bg-primary/5 text-primary-foreground/80",
                                "hover:border-primary hover:bg-primary/10 hover:shadow-md",
                                "transition-all duration-200 flex items-center justify-center gap-2"
                            )}
                        >
                            <Plus className="w-5 h-5 text-muted-foreground" />
                            <span className="text-sm font-medium text-foreground">Create New Space</span>
                        </button>

                        {/* Spaces List */}
                        <div className="grid grid-cols-2 gap-4">
                            {filteredSpaces.map(space => {
                                const stats = getSpaceStats(space.id)
                                const spaceCrews = crews.filter(c => c.space_id === space.id)
                                return (
                                    <div
                                        key={space.id}
                                        className={cn(
                                            "p-5 rounded-xl border",
                                            "bg-white dark:bg-gray-800",
                                            "border-gray-200 dark:border-gray-700",
                                            "hover:shadow-lg hover:border-blue-300 dark:hover:border-blue-700",
                                            "transition-all duration-200 cursor-pointer",
                                            selectedSpace === space.id && "ring-2 ring-blue-500 border-blue-500"
                                        )}
                                        onClick={() => setSelectedSpace(selectedSpace === space.id ? null : space.id)}
                                    >
                                        <div className="flex items-start justify-between mb-4">
                                            <div className="flex items-center gap-3">
                                                <div className={cn(
                                                    "w-12 h-12 rounded-lg flex items-center justify-center text-white font-bold",
                                                    "bg-blue-500" // Default color since Space API doesn't have color field
                                                )}>
                                                    {space.name.charAt(0).toUpperCase()}
                                                </div>
                                                <div>
                                                    <h3 className="font-semibold text-foreground mb-1">{space.name}</h3>
                                                    <p className="text-xs text-muted-foreground line-clamp-1">{space.description}</p>
                                                </div>
                                            </div>
                                            <button
                                                onClick={(e) => {
                                                    e.stopPropagation()
                                                    deleteSpace(space.id)
                                                }}
                                                className="p-2 rounded hover:bg-red-50 dark:hover:bg-red-900/20 text-red-500"
                                            >
                                                <Trash2 className="w-4 h-4" />
                                            </button>
                                        </div>

                                        {/* Stats */}
                                        <div className="grid grid-cols-3 gap-2 mb-4">
                                            <div className="text-center p-2 rounded bg-gray-50 dark:bg-gray-900/30">
                                                <p className="text-lg font-semibold text-foreground">{stats.crews}</p>
                                                <p className="text-[10px] text-muted-foreground">Crews</p>
                                            </div>
                                            <div className="text-center p-2 rounded bg-gray-50 dark:bg-gray-900/30">
                                                <p className="text-lg font-semibold text-foreground">{stats.members}</p>
                                                <p className="text-[10px] text-muted-foreground">Members</p>
                                            </div>
                                            <div className="text-center p-2 rounded bg-gray-50 dark:bg-gray-900/30">
                                                <p className="text-lg font-semibold text-foreground">{stats.connections}</p>
                                                <p className="text-[10px] text-muted-foreground">Connections</p>
                                            </div>
                                        </div>

                                        {/* Crews List */}
                                        {spaceCrews.length > 0 && (
                                            <div className="space-y-2">
                                                <p className="text-xs font-medium text-muted-foreground mb-2">Crews:</p>
                                                {spaceCrews.map(crew => (
                                                    <div
                                                        key={crew.id}
                                                        className={cn(
                                                            "p-2 rounded border",
                                                            "bg-gray-50 dark:bg-gray-900/30",
                                                            "border-gray-200 dark:border-gray-700",
                                                            "flex items-center justify-between"
                                                        )}
                                                    >
                                                        <span className="text-xs text-foreground">{crew.name}</span>
                                                        <span className="text-[10px] text-muted-foreground">
                                                            {getCrewMembers(crew.id).length} members
                                                        </span>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                ) : (
                    <div className="space-y-4">
                        {/* Filter by Space */}
                        {spaces.length > 0 && (
                            <div className="flex items-center gap-2">
                                <span className="text-xs text-muted-foreground">Filter by Space:</span>
                                <select
                                    value={selectedSpace || 'all'}
                                    onChange={(e) => setSelectedSpace(e.target.value === 'all' ? null : e.target.value)}
                                    className={cn(
                                        "h-8 px-3 pr-8 rounded-lg text-xs border",
                                        isDark 
                                            ? "bg-white/4 border-white/8 text-foreground" 
                                            : "bg-white border-black/8 text-foreground",
                                        "appearance-none cursor-pointer"
                                    )}
                                >
                                    <option value="all">All Spaces</option>
                                    {spaces.map(space => (
                                        <option key={space.id} value={space.id}>{space.name}</option>
                                    ))}
                                </select>
                            </div>
                        )}

                        {/* Add Crew Button */}
                        <button
                            onClick={() => setShowAddCrewModal(true)}
                            className={cn(
                                "w-full p-4 rounded-xl border-2 border-dashed",
                                "border-primary/40 bg-primary/5 text-primary-foreground/80",
                                "hover:border-primary hover:bg-primary/10 hover:shadow-md",
                                "transition-all duration-200 flex items-center justify-center gap-2"
                            )}
                        >
                            <Plus className="w-5 h-5 text-muted-foreground" />
                            <span className="text-sm font-medium text-foreground">Create New Crew</span>
                        </button>

                        {/* Crews List */}
                        <div className="grid grid-cols-2 gap-4">
                            {filteredCrews.map(crew => {
                                const space = spaces.find(s => s.id === crew.space_id)
                                const members = getCrewMembers(crew.id)
                                return (
                                    <div
                                        key={crew.id}
                                        className={cn(
                                            "p-5 rounded-xl border",
                                            "bg-white dark:bg-gray-800",
                                            "border-gray-200 dark:border-gray-700",
                                            "hover:shadow-lg hover:border-blue-300 dark:hover:border-blue-700",
                                            "transition-all duration-200 cursor-pointer",
                                            selectedCrew === crew.id && "ring-2 ring-blue-500 border-blue-500"
                                        )}
                                        onClick={() => setSelectedCrew(selectedCrew === crew.id ? null : crew.id)}
                                    >
                                        <div className="flex items-start justify-between mb-4">
                                            <div className="flex-1">
                                                <h3 className="font-semibold text-foreground mb-1">{crew.name}</h3>
                                                <p className="text-xs text-muted-foreground mb-2 line-clamp-1">{crew.description}</p>
                                                {space && (
                                                    <div className="flex items-center gap-1.5">
                                                        <div className={cn(
                                                            "w-2 h-2 rounded-full",
                                                            "bg-blue-500" // Default color since Space API doesn't have color field
                                                        )} />
                                                        <span className="text-[10px] text-muted-foreground">{space.name}</span>
                                                    </div>
                                                )}
                                            </div>
                                            <button
                                                onClick={(e) => {
                                                    e.stopPropagation()
                                                    deleteCrew(crew.id)
                                                }}
                                                className="p-2 rounded hover:bg-red-50 dark:hover:bg-red-900/20 text-red-500"
                                            >
                                                <Trash2 className="w-4 h-4" />
                                            </button>
                                        </div>

                                        {/* Members */}
                                        {members.length > 0 && (
                                            <div className="space-y-2">
                                                <p className="text-xs font-medium text-muted-foreground mb-2">Members:</p>
                                                {members.map(({ user, role }) => (
                                                    <div
                                                        key={`${crew.id}-${user?.id}`}
                                                        className={cn(
                                                            "p-2 rounded border",
                                                            "bg-gray-50 dark:bg-gray-900/30",
                                                            "border-gray-200 dark:border-gray-700",
                                                            "flex items-center justify-between"
                                                        )}
                                                    >
                                                        <div className="flex items-center gap-2">
                                                            <div className={cn(
                                                                "w-6 h-6 rounded-full flex items-center justify-center text-white text-xs font-semibold",
                                                                user?.avatar === 'F' && "bg-green-500",
                                                                user?.avatar === 'K' && "bg-teal-500",
                                                                user?.avatar === 'L' && "bg-red-500",
                                                                "bg-blue-500"
                                                            )}>
                                                                {user?.avatar}
                                                            </div>
                                                            <span className="text-xs text-foreground">{user?.name}</span>
                                                        </div>
                                                        <span className={cn(
                                                            "text-[10px] px-2 py-0.5 rounded",
                                                            role === 'commander' && "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300",
                                                            role === 'navigator' && "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300",
                                                            role === 'explorer' && "bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300",
                                                            role === 'guest' && "bg-gray-100 dark:bg-gray-900/30 text-gray-700 dark:text-gray-300"
                                                        )}>
                                                            {role}
                                                        </span>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                )}
            </div>

            {/* Add Space Modal */}
            <AnimatePresence>
                {showAddSpaceModal && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 z-[110] flex items-center justify-center"
                    >
                        <div 
                            className="fixed inset-0 bg-black/20 backdrop-blur-sm"
                            onClick={() => {
                                setShowAddSpaceModal(false)
                                setSpaceFormData({ name: '', description: '', color: 'blue' })
                            }}
                        />
                        <motion.div
                            initial={{ opacity: 0, scale: 0.95 }}
                            animate={{ opacity: 1, scale: 1 }}
                            exit={{ opacity: 0, scale: 0.95 }}
                            className={cn(
                                "relative w-[500px] rounded-xl",
                                "bg-white dark:bg-gray-800",
                                "border border-gray-200 dark:border-gray-700",
                                "shadow-2xl p-6"
                            )}
                            onClick={(e) => e.stopPropagation()}
                        >
                            <div className="flex items-center justify-between mb-4">
                                <h3 className="text-lg font-semibold text-foreground">Create New Space</h3>
                                <button
                                    onClick={() => {
                                        setShowAddSpaceModal(false)
                                        setSpaceFormData({ name: '', description: '', color: 'blue' })
                                    }}
                                    className="w-8 h-8 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center justify-center"
                                >
                                    <X className="w-4 h-4" />
                                </button>
                            </div>

                            <div className="space-y-4">
                                <div>
                                    <label className="text-xs font-medium text-foreground mb-1.5 block">
                                        Name <span className="text-red-500">*</span>
                                    </label>
                                    <Input
                                        value={spaceFormData.name}
                                        onChange={(e) => setSpaceFormData({ ...spaceFormData, name: e.target.value })}
                                        placeholder="e.g., Financeiro"
                                        className={cn(
                                            "h-9 text-xs",
                                            isDark 
                                                ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                                : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                                        )}
                                    />
                                </div>

                                <div>
                                    <label className="text-xs font-medium text-foreground mb-1.5 block">
                                        Description
                                    </label>
                                    <textarea
                                        value={spaceFormData.description}
                                        onChange={(e) => setSpaceFormData({ ...spaceFormData, description: e.target.value })}
                                        placeholder="Optional description"
                                        rows={3}
                                        className={cn(
                                            "w-full rounded-lg text-xs p-2.5 resize-none",
                                            isDark 
                                                ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                                : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                                        )}
                                    />
                                </div>

                                <div>
                                    <label className="text-xs font-medium text-foreground mb-1.5 block">
                                        Color
                                    </label>
                                    <div className="grid grid-cols-6 gap-2">
                                        {colorOptions.map(color => (
                                            <button
                                                key={color.value}
                                                onClick={() => setSpaceFormData({ ...spaceFormData, color: color.value })}
                                                className={cn(
                                                    "h-10 rounded-lg border-2 transition-all",
                                                    spaceFormData.color === color.value
                                                        ? "border-blue-500 ring-2 ring-blue-200 dark:ring-blue-800"
                                                        : "border-gray-200 dark:border-gray-700 hover:border-gray-300"
                                                )}
                                            >
                                                <div className={cn("w-full h-full rounded", color.class)} />
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            </div>

                            <div className="flex items-center justify-end gap-3 pt-4 mt-4 border-t">
                                <button
                                    onClick={() => {
                                        setShowAddSpaceModal(false)
                                        setSpaceFormData({ name: '', description: '', color: 'blue' })
                                    }}
                                    className={cn(
                                        "px-4 py-2 rounded-lg text-sm font-medium",
                                        "hover:bg-gray-100 dark:hover:bg-gray-700",
                                        "transition-colors"
                                    )}
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handleAddSpace}
                                    disabled={!spaceFormData.name}
                                    className={cn(
                                        "px-4 py-2 rounded-lg text-sm font-medium",
                                        "bg-primary hover:bg-primary/90 text-primary-foreground",
                                        "disabled:opacity-50 disabled:cursor-not-allowed",
                                        "transition-colors"
                                    )}
                                >
                                    Create Space
                                </button>
                            </div>
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* Add Crew Modal */}
            <AnimatePresence>
                {showAddCrewModal && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 z-[110] flex items-center justify-center"
                    >
                        <div 
                            className="fixed inset-0 bg-black/20 backdrop-blur-sm"
                            onClick={() => {
                                setShowAddCrewModal(false)
                                setCrewFormData({ name: '', description: '', spaceId: '' })
                            }}
                        />
                        <motion.div
                            initial={{ opacity: 0, scale: 0.95 }}
                            animate={{ opacity: 1, scale: 1 }}
                            exit={{ opacity: 0, scale: 0.95 }}
                            className={cn(
                                "relative w-[500px] rounded-xl",
                                "bg-white dark:bg-gray-800",
                                "border border-gray-200 dark:border-gray-700",
                                "shadow-2xl p-6"
                            )}
                            onClick={(e) => e.stopPropagation()}
                        >
                            <div className="flex items-center justify-between mb-4">
                                <h3 className="text-lg font-semibold text-foreground">Create New Crew</h3>
                                <button
                                    onClick={() => {
                                        setShowAddCrewModal(false)
                                        setCrewFormData({ name: '', description: '', spaceId: '' })
                                    }}
                                    className="w-8 h-8 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center justify-center"
                                >
                                    <X className="w-4 h-4" />
                                </button>
                            </div>

                            <div className="space-y-4">
                                <div>
                                    <label className="text-xs font-medium text-foreground mb-1.5 block">
                                        Name <span className="text-red-500">*</span>
                                    </label>
                                    <Input
                                        value={crewFormData.name}
                                        onChange={(e) => setCrewFormData({ ...crewFormData, name: e.target.value })}
                                        placeholder="e.g., Salários"
                                        className={cn(
                                            "h-9 text-xs",
                                            isDark 
                                                ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                                : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                                        )}
                                    />
                                </div>

                                <div>
                                    <label className="text-xs font-medium text-foreground mb-1.5 block">
                                        Space <span className="text-red-500">*</span>
                                    </label>
                                    <div className="relative">
                                        <select
                                            value={crewFormData.spaceId}
                                            onChange={(e) => setCrewFormData({ ...crewFormData, spaceId: e.target.value })}
                                            className={cn(
                                                "h-9 w-full px-3 pr-8 rounded-lg text-xs border appearance-none cursor-pointer",
                                                isDark 
                                                    ? "bg-white/4 border-white/8 text-foreground" 
                                                    : "bg-white border-black/8 text-foreground"
                                            )}
                                        >
                                            <option value="">Select a space</option>
                                            {spaces.map(space => (
                                                <option key={space.id} value={space.id}>{space.name}</option>
                                            ))}
                                        </select>
                                        <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                                    </div>
                                </div>

                                <div>
                                    <label className="text-xs font-medium text-foreground mb-1.5 block">
                                        Description
                                    </label>
                                    <textarea
                                        value={crewFormData.description}
                                        onChange={(e) => setCrewFormData({ ...crewFormData, description: e.target.value })}
                                        placeholder="Optional description"
                                        rows={3}
                                        className={cn(
                                            "w-full rounded-lg text-xs p-2.5 resize-none",
                                            isDark 
                                                ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                                : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                                        )}
                                    />
                                </div>
                            </div>

                            <div className="flex items-center justify-end gap-3 pt-4 mt-4 border-t">
                                <button
                                    onClick={() => {
                                        setShowAddCrewModal(false)
                                        setCrewFormData({ name: '', description: '', spaceId: '' })
                                    }}
                                    className={cn(
                                        "px-4 py-2 rounded-lg text-sm font-medium",
                                        "hover:bg-gray-100 dark:hover:bg-gray-700",
                                        "transition-colors"
                                    )}
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handleAddCrew}
                                    disabled={!crewFormData.name || !crewFormData.spaceId}
                                    className={cn(
                                        "px-4 py-2 rounded-lg text-sm font-medium",
                                        "bg-primary hover:bg-primary/90 text-primary-foreground",
                                        "disabled:opacity-50 disabled:cursor-not-allowed",
                                        "transition-colors"
                                    )}
                                >
                                    Create Crew
                                </button>
                            </div>
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    )
}

// ============================================
// CONNECTION PERMISSIONS SECTION - Granular Access Control
// ============================================
export function ConnectionPermissionsSection({ isDark }: { isDark: boolean }) {
    const [viewMode, setViewMode] = useState<'by-connection' | 'by-space-crew'>('by-connection')
    const [selectedConnection, setSelectedConnection] = useState<string | null>(null)
    const [selectedSpace, setSelectedSpace] = useState<string | null>(null)
    const [selectedCrew, setSelectedCrew] = useState<string | null>(null)
    
    // Load connections from API instead of mock data
    const [connections, setConnections] = useState<DataConnection[]>([])
    
    useEffect(() => {
        const loadConnections = async () => {
            try {
                const apiConnections = await connectionsApi.listConnections()
                const formattedConnections: DataConnection[] = await Promise.all(
                    apiConnections.map(async (conn: Connection) => {
                        let metadata: ConnectionMetadata | undefined
                        try {
                            const metadataResponse = await connectionsApi.getConnectionMetadata(conn.id)
                            metadata = {
                                tables: (metadataResponse.tables || []).map((t: any) => ({
                                    name: t.name,
                                    schema: t.schema || t.schema_name,
                                    rowCount: t.row_count,
                                    columns: (t.columns || []).map((col: any) => ({
                                        name: col.name,
                                        type: col.type,
                                        nullable: col.nullable,
                                        description: col.description
                                    }))
                                })),
                                schemas: (metadataResponse.schemas || []).map((s: any) => 
                                    typeof s === 'string' 
                                        ? { name: s, tables: [] }
                                        : { name: s.name || s, tables: s.tables || [] }
                                ),
                                lastMetadataUpdate: metadataResponse.last_metadata_update
                            }
                        } catch (err) {
                            console.warn(`Failed to load metadata for connection ${conn.id}:`, err)
                        }
                        
                        const validStatus = (conn.status === 'active' || conn.status === 'inactive' || conn.status === 'error') 
                            ? conn.status 
                            : 'inactive' as 'active' | 'inactive' | 'error'
                        
                        return {
                            id: conn.id,
                            name: conn.name,
                            connectorId: conn.connector_id,
                            status: validStatus,
                            lastSync: conn.last_sync,
                            nextSync: conn.next_sync,
                            syncFrequency: conn.sync_frequency || '0 */6 * * *',
                            config: conn.config || {},
                            description: conn.description || '',
                            createdAt: conn.created_at || new Date().toISOString(),
                            updatedAt: conn.updated_at || new Date().toISOString(),
                            metadata
                        }
                    })
                )
                setConnections(formattedConnections)
            } catch (error) {
                console.error('Error loading connections:', error)
            }
        }
        loadConnections()
    }, [])
    
    const [spaces] = useState<Space[]>([])
    const [crews] = useState<ApiCrew[]>([])
    
    const [permissions, setPermissions] = useState<ApiConnectionPermission[]>([])

    useEffect(() => {
        const loadPermissions = async () => {
            try {
                // Load permissions for all connections
                const allConnections = await connectionsApi.listConnections()
                const allPerms: ApiConnectionPermission[] = []
                for (const conn of allConnections) {
                    try {
                        const connPerms = await permissionsApi.getConnectionPermissions(conn.id)
                        allPerms.push(...connPerms)
                    } catch (err) {
                        console.warn(`Failed to load permissions for connection ${conn.id}:`, err)
                    }
                }
                setPermissions(allPerms)
            } catch (error) {
                console.error('Error loading permissions:', error)
            }
        }
        loadPermissions()
    }, [])

    const getConnectionPermissions = (connectionId: string) => {
        return permissions.filter(p => p.connection_id === connectionId)
    }

    const getSpacePermissions = (spaceId: string) => {
        return permissions.filter(p => p.space_id === spaceId)
    }

    const getCrewPermissions = (crewId: string) => {
        return permissions.filter(p => p.crew_id === crewId)
    }

    const addPermission = (permission: ApiConnectionPermission) => {
        setPermissions([...permissions, permission])
    }

    const removePermission = (connectionId: string, spaceId?: string, crewId?: string) => {
        setPermissions(permissions.filter(p => 
            !(p.connection_id === connectionId && 
              (spaceId ? p.space_id === spaceId : !p.space_id) &&
              (crewId ? p.crew_id === crewId : !p.crew_id))
        ))
    }

    const updateTableAccess = (connectionId: string, crewId: string, tables: string[]) => {
        setPermissions(permissions.map(p => 
            p.connection_id === connectionId && p.crew_id === crewId
                ? { ...p, table_access: tables, access_level: 'custom' }
                : p
        ))
    }

    return (
        <div className="h-full flex flex-col">
            {/* Header */}
            <div className={cn(
                "px-5 py-4 border-b",
                isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
            )}>
                <div className="flex items-center justify-between mb-3">
                    <div className="flex-1">
                        <p className="text-xs text-muted-foreground mb-1">
                            Manage access to connections and tables. Grant permissions at Space or Crew level with granular table access control.
                        </p>
                    </div>
                </div>

                {/* View Mode Toggle */}
                <div className="flex gap-2">
                    <button
                        onClick={() => setViewMode('by-connection')}
                        className={cn(
                            "px-4 py-2 rounded-lg text-sm font-medium transition-colors",
                            viewMode === 'by-connection'
                                ? "bg-blue-500 text-white"
                                : "bg-gray-100 dark:bg-gray-800 text-foreground hover:bg-gray-200 dark:hover:bg-gray-700"
                        )}
                    >
                        By Connection
                    </button>
                    <button
                        onClick={() => setViewMode('by-space-crew')}
                        className={cn(
                            "px-4 py-2 rounded-lg text-sm font-medium transition-colors",
                            viewMode === 'by-space-crew'
                                ? "bg-blue-500 text-white"
                                : "bg-gray-100 dark:bg-gray-800 text-foreground hover:bg-gray-200 dark:hover:bg-gray-700"
                        )}
                    >
                        By Space/Crew
                    </button>
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-5">
                {viewMode === 'by-connection' ? (
                    <div className="space-y-4">
                        <h3 className="text-sm font-semibold text-foreground mb-3">Select a connection to manage permissions</h3>
                        <div className="grid grid-cols-2 gap-4">
                            {connections.map(conn => {
                                const connPermissions = getConnectionPermissions(conn.id)
                                const spacePerms = connPermissions.filter(p => p.space_id)
                                const crewPerms = connPermissions.filter(p => p.crew_id)
                                
                                return (
                                    <div
                                        key={conn.id}
                                        className={cn(
                                            "p-4 rounded-xl border",
                                            "bg-white dark:bg-gray-800",
                                            "border-gray-200 dark:border-gray-700",
                                            "hover:shadow-lg hover:border-blue-300 dark:hover:border-blue-700",
                                            "transition-all duration-200 cursor-pointer",
                                            selectedConnection === conn.id && "ring-2 ring-blue-500 border-blue-500"
                                        )}
                                        onClick={() => setSelectedConnection(selectedConnection === conn.id ? null : conn.id)}
                                    >
                                        <div className="flex items-center justify-between mb-3">
                                            <h4 className="font-semibold text-foreground">{conn.name}</h4>
                                            <span className={cn(
                                                "text-xs px-2 py-1 rounded",
                                                conn.status === 'active' 
                                                    ? "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400"
                                                    : "bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300"
                                            )}>
                                                {conn.status}
                                            </span>
                                        </div>
                                        
                                        {selectedConnection === conn.id && (
                                            <div className="mt-4 space-y-4 pt-4 border-t">
                                                {/* Space Permissions */}
                                                <div>
                                                    <p className="text-xs font-medium text-foreground mb-2">Space Access:</p>
                                                    <div className="space-y-2">
                                                        {spacePerms.map(perm => {
                                                            const space = spaces.find(s => s.id === perm.space_id)
                                                            return space ? (
                                                                <div key={perm.space_id} className="flex items-center justify-between p-2 rounded bg-gray-50 dark:bg-gray-900/30">
                                                                    <span className="text-xs text-foreground">{space.name}</span>
                                                                    <div className="flex items-center gap-2">
                                                                        <span className="text-[10px] text-muted-foreground">{perm.access_level}</span>
                                                                        <button
                                                                            onClick={(e) => {
                                                                                e.stopPropagation()
                                                                                removePermission(perm.id)
                                                                            }}
                                                                            className="p-1 rounded hover:bg-red-50 dark:hover:bg-red-900/20 text-red-500"
                                                                        >
                                                                            <X className="w-3 h-3" />
                                                                        </button>
                                                                    </div>
                                                                </div>
                                                            ) : null
                                                        })}
                                                        <button
                                                            onClick={(e) => {
                                                                e.stopPropagation()
                                                                // Open modal to add space permission
                                                            }}
                                                            className="w-full p-2 rounded border border-dashed border-gray-300 dark:border-gray-600 text-xs text-muted-foreground hover:border-blue-400 hover:text-blue-500"
                                                        >
                                                            + Add Space Access
                                                        </button>
                                                    </div>
                                                </div>

                                                {/* Crew Permissions */}
                                                {conn.metadata?.tables && (
                                                    <div>
                                                        <p className="text-xs font-medium text-foreground mb-2">Crew Access (with table-level control):</p>
                                                        <div className="space-y-2">
                                                            {crewPerms.map(perm => {
                                                                const crew = crews.find(c => c.id === perm.crew_id)
                                                                return crew ? (
                                                                    <div key={perm.crew_id} className="p-2 rounded bg-gray-50 dark:bg-gray-900/30">
                                                                        <div className="flex items-center justify-between mb-2">
                                                                            <span className="text-xs font-medium text-foreground">{crew.name}</span>
                                                                            <button
                                                                                onClick={(e) => {
                                                                                    e.stopPropagation()
                                                                                    removePermission(perm.id)
                                                                                }}
                                                                                className="p-1 rounded hover:bg-red-50 dark:hover:bg-red-900/20 text-red-500"
                                                                            >
                                                                                <X className="w-3 h-3" />
                                                                            </button>
                                                                        </div>
                                                                        <div className="space-y-1">
                                                                            <p className="text-[10px] text-muted-foreground mb-1">Tables:</p>
                                                                            <div className="flex flex-wrap gap-1">
                                                                                {conn.metadata?.tables?.map(table => (
                                                                                    <label
                                                                                        key={table.name}
                                                                                        className={cn(
                                                                                            "text-[10px] px-2 py-1 rounded cursor-pointer",
                                                                                            perm.table_access?.includes(table.name)
                                                                                                ? "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                                                                                                : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"
                                                                                        )}
                                                                                    >
                                                                                        <input
                                                                                            type="checkbox"
                                                                                            checked={perm.table_access?.includes(table.name) || false}
                                                                                            onChange={(e) => {
                                                                                                const currentTables = perm.table_access || []
                                                                                                const newTables = e.target.checked
                                                                                                    ? [...currentTables, table.name]
                                                                                                    : currentTables.filter(t => t !== table.name)
                                                                                                updateTableAccess(conn.id, perm.crew_id!, newTables)
                                                                                            }}
                                                                                            className="hidden"
                                                                                        />
                                                                                        {table.name}
                                                                                    </label>
                                                                                ))}
                                                                            </div>
                                                                        </div>
                                                                    </div>
                                                                ) : null
                                                            })}
                                                            <button
                                                                onClick={(e) => {
                                                                    e.stopPropagation()
                                                                    // Open modal to add crew permission
                                                                }}
                                                                className="w-full p-2 rounded border border-dashed border-gray-300 dark:border-gray-600 text-xs text-muted-foreground hover:border-blue-400 hover:text-blue-500"
                                                            >
                                                                + Add Crew Access
                                                            </button>
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                ) : (
                    <div className="space-y-4">
                        {/* Spaces List */}
                        <div>
                            <h3 className="text-sm font-semibold text-foreground mb-3">Spaces</h3>
                            <div className="space-y-2">
                                {spaces.map(space => {
                                    const spacePerms = getSpacePermissions(space.id)
                                    const spaceCrews = crews.filter(c => c.space_id === space.id)
                                    
                                    return (
                                        <div
                                            key={space.id}
                                            className={cn(
                                                "p-4 rounded-xl border",
                                                "bg-white dark:bg-gray-800",
                                                "border-gray-200 dark:border-gray-700",
                                                "hover:shadow-lg hover:border-blue-300 dark:hover:border-blue-700",
                                                "transition-all duration-200 cursor-pointer",
                                                selectedSpace === space.id && "ring-2 ring-blue-500 border-blue-500"
                                            )}
                                            onClick={() => {
                                                setSelectedSpace(selectedSpace === space.id ? null : space.id)
                                                setSelectedCrew(null)
                                            }}
                                        >
                                            <div className="flex items-center justify-between mb-3">
                                                <h4 className="font-semibold text-foreground">{space.name}</h4>
                                                <span className="text-xs text-muted-foreground">{spaceCrews.length} crews</span>
                                            </div>
                                            
                                            {selectedSpace === space.id && (
                                                <div className="mt-4 space-y-4 pt-4 border-t">
                                                    {/* Connections accessible by this space */}
                                                    <div>
                                                        <p className="text-xs font-medium text-foreground mb-2">Connections:</p>
                                                        <div className="space-y-2">
                                                            {spacePerms.map(perm => {
                                                                const conn = connections.find(c => c.id === perm.connection_id)
                                                                return conn ? (
                                                                    <div key={perm.connection_id} className="flex items-center justify-between p-2 rounded bg-gray-50 dark:bg-gray-900/30">
                                                                        <span className="text-xs text-foreground">{conn.name}</span>
                                                                        <span className="text-[10px] text-muted-foreground">{perm.access_level}</span>
                                                                    </div>
                                                                ) : null
                                                            })}
                                                        </div>
                                                    </div>

                                                    {/* Crews in this space */}
                                                    <div>
                                                        <p className="text-xs font-medium text-foreground mb-2">Crews:</p>
                                                        <div className="space-y-2">
                                                            {spaceCrews.map(crew => {
                                                                const crewPerms = getCrewPermissions(crew.id)
                                                                return (
                                                                    <div
                                                                        key={crew.id}
                                                                        className={cn(
                                                                            "p-2 rounded border",
                                                                            "bg-gray-50 dark:bg-gray-900/30",
                                                                            "border-gray-200 dark:border-gray-700",
                                                                            "cursor-pointer",
                                                                            selectedCrew === crew.id && "ring-2 ring-blue-500 border-blue-500"
                                                                        )}
                                                                        onClick={(e) => {
                                                                            e.stopPropagation()
                                                                            setSelectedCrew(selectedCrew === crew.id ? null : crew.id)
                                                                        }}
                                                                    >
                                                                        <div className="flex items-center justify-between mb-2">
                                                                            <span className="text-xs font-medium text-foreground">{crew.name}</span>
                                                                            <span className="text-[10px] text-muted-foreground">{crewPerms.length} connections</span>
                                                                        </div>
                                                                        
                                                                        {selectedCrew === crew.id && crewPerms.length > 0 && (
                                                                            <div className="mt-2 space-y-1 pt-2 border-t">
                                                                                {crewPerms.map(perm => {
                                                                                    const conn = connections.find(c => c.id === perm.connection_id)
                                                                                    return conn ? (
                                                                                        <div key={perm.connection_id} className="text-xs">
                                                                                            <span className="text-foreground">{conn.name}</span>
                                                                                            {perm.table_access && perm.table_access.length > 0 && (
                                                                                                <span className="text-muted-foreground ml-2">
                                                                                                    ({perm.table_access?.length || 0} tables)
                                                                                                </span>
                                                                                            )}
                                                                                        </div>
                                                                                    ) : null
                                                                                })}
                                                                            </div>
                                                                        )}
                                                                    </div>
                                                                )
                                                            })}
                                                        </div>
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    )
                                })}
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}

// ============================================
// USERS SECTION - Complete Table Interface
// ============================================
export function UsersSection({ isDark }: { isDark: boolean }) {
    // Use real stores
    const { crews, fetchCrews } = useCrewStore()
    const { spaces, fetchSpaces } = useSpaceStore()
    
    // State for user's crew memberships
    const [userCrewMemberships, setUserCrewMemberships] = useState<Record<string, ApiCrewMember[]>>({})
    const [isLoadingCrews, setIsLoadingCrews] = useState(false)
    
    // State for connections
    const [connections, setConnections] = useState<Connection[]>([])
    
    const [users, setUsers] = useState<(ApiUser & { status?: string; lastActive?: string })[]>([])
    const [searchQuery, setSearchQuery] = useState('')
    const [filterRole, setFilterRole] = useState('all')
    const [filterStatus, setFilterStatus] = useState('all')
    const [filterSpace, setFilterSpace] = useState('all')
    const [filterCrew, setFilterCrew] = useState('all')
    const [selectedUser, setSelectedUser] = useState<string | null>(null)
    const [viewMode, setViewMode] = useState<'list' | 'detail' | 'add'>('list')
    const [currentPage, setCurrentPage] = useState(1)
    const [itemsPerPage, setItemsPerPage] = useState(10)
    const [deleteModalOpen, setDeleteModalOpen] = useState(false)
    const [itemToDelete, setItemToDelete] = useState<{ id: string; name: string } | null>(null)
    const [formData, setFormData] = useState({ name: '', email: '', status: 'active' })
    
    // Load users, crews and spaces on mount
    useEffect(() => {
        const loadData = async () => {
            try {
                const backendUsers = await usersApi.listUsers()
                // Map backend roles to frontend roles
                const mapRoleToFrontend = (role: string): string => {
                    const roleMap: Record<string, string> = {
                        'user': 'Member',
                        'admin': 'Team Admin',
                        'viewer': 'Member',
                    }
                    return roleMap[role] || 'Member'
                }
                // Map backend users into local shape with default status/lastActive
                setUsers(
                    backendUsers.map((u) => ({
                        ...u,
                        role: mapRoleToFrontend(u.role), // Map backend role to frontend format
                        status: 'active',
                        lastActive: '',
                    }))
                )
            } catch (error) {
                console.error('Error loading users:', error)
            }
            fetchCrews().catch(console.error)
            fetchSpaces().catch(console.error)
            
            // Load connections
            try {
                const apiConnections = await connectionsApi.listConnections()
                setConnections(apiConnections)
            } catch (error) {
                console.error('Error loading connections:', error)
            }
        }
        loadData()
    }, [fetchCrews, fetchSpaces])
    
    // Load user's crew memberships and permissions when editing
    useEffect(() => {
        if (selectedUser && viewMode === 'detail') {
            loadUserCrewMemberships(selectedUser)
        }
    }, [selectedUser, viewMode])
    
    const loadUserCrewMemberships = async (userId: string) => {
        setIsLoadingCrews(true)
        try {
            // Get all crews and check which ones the user belongs to
            const allCrews = await crewsApi.listCrews()
            const memberships: ApiCrewMember[] = []
            
            for (const crew of allCrews) {
                try {
                    const members = await crewsApi.getCrewMembers(crew.id)
                    const userMember = members.find(m => m.user_id === userId)
                    if (userMember) {
                        memberships.push(userMember)
                    }
                } catch (error) {
                    // Skip crews user doesn't have access to
                    console.error(`Error loading members for crew ${crew.id}:`, error)
                }
            }
            
            setUserCrewMemberships(prev => ({ ...prev, [userId]: memberships }))
        } catch (error) {
            console.error('Error loading user crew memberships:', error)
        } finally {
            setIsLoadingCrews(false)
        }
    }
    
    // Get user's crews and spaces
    const getUserCrews = (userId: string) => {
        const memberships = userCrewMemberships[userId] || []
        return memberships.map(m => {
            const crew = crews.find(c => c.id === m.crew_id)
            const space = crew ? spaces.find(s => s.id === crew.space_id) : null
            return { ...m, crew, space }
        })
    }
    
    const getUserSpaces = (userId: string) => {
        const userCrews = getUserCrews(userId)
        const spaceIds = new Set(userCrews.map(uc => uc.space?.id).filter(Boolean))
        return spaces.filter(s => spaceIds.has(s.id))
    }

    const filteredUsers = users.filter(user => {
        const matchesSearch = user.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
                            user.email.toLowerCase().includes(searchQuery.toLowerCase())
        const matchesRole = filterRole === 'all' || user.role === filterRole
        const matchesStatus = filterStatus === 'all' || user.status === filterStatus
        
        // Filter by space
        const userSpaces = getUserSpaces(user.id)
        const matchesSpace = filterSpace === 'all' || userSpaces.some(s => s.id === filterSpace)
        
        // Filter by crew
        const userCrews = getUserCrews(user.id)
        const matchesCrew = filterCrew === 'all' || userCrews.some(uc => uc.crew_id === filterCrew)
        
        return matchesSearch && matchesRole && matchesStatus && matchesSpace && matchesCrew
    })

    const paginatedUsers = filteredUsers.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage)
    const totalPages = Math.ceil(filteredUsers.length / itemsPerPage)
    const uniqueRoles = Array.from(new Set(users.map(u => u.role)))

    const stats = {
        total: users.length,
        active: users.filter(u => u.status === 'active').length,
        admins: users.filter(u => u.role.includes('Admin')).length,
    }

    const getAvatarColor = (initial?: string | null) => {
        const colors = ['bg-green-500', 'bg-teal-500', 'bg-red-500', 'bg-blue-500', 'bg-purple-500']
        const safeInitial = (initial && initial.length > 0) ? initial : 'U'
        return colors[safeInitial.charCodeAt(0) % colors.length]
    }
    
    const handleSaveUser = async () => {
        try {
            if (selectedUser) {
                // Update existing user
                await usersApi.updateUser(selectedUser, {
                    name: formData.name,
                    email: formData.email,
                })
            } else {
                // Create new user - generate a temporary password
                // In a real scenario, you might want to show a password field or use invite flow
                await usersApi.createUser({
                    name: formData.name,
                    email: formData.email,
                    password: 'TempPassword123!', // Temporary password - user should change on first login
                    role: 'user', // Default role
                })
            }
            
            // Reload users list from backend
            const backendUsers = await usersApi.listUsers()
            // Map backend roles to frontend roles for display
            const mapRoleToFrontend = (role: string): string => {
                const roleMap: Record<string, string> = {
                    'user': 'Member',
                    'admin': 'Team Admin',
                    'viewer': 'Member',
                }
                return roleMap[role] || 'Member'
            }
            setUsers(
                backendUsers.map((u) => ({
                    ...u,
                    role: mapRoleToFrontend(u.role), // Map back to frontend role format for display
                    status: 'active',
                    lastActive: '',
                }))
            )
            
            // Reset
            setViewMode('list')
            setSelectedUser(null)
            setFormData({ name: '', email: '', status: 'active' })
        } catch (error) {
            console.error('Error saving user:', error)
            alert(`Erro ao salvar usuário: ${error instanceof Error ? error.message : 'Erro desconhecido'}`)
        }
    }
    
    const handleCancelUser = () => {
        setViewMode('list')
        setSelectedUser(null)
        setFormData({ name: '', email: '', status: 'active' })
    }
    
    // Initialize form data when editing
    useEffect(() => {
        if (viewMode === 'detail' && selectedUser) {
            const currentUser = users.find(u => u.id === selectedUser)
            if (currentUser) {
                setFormData({
                    name: currentUser.name,
                    email: currentUser.email,
                    status: currentUser.status || 'active'
                })
            }
        } else if (viewMode === 'add') {
            setFormData({ name: '', email: '', status: 'active' })
        }
    }, [viewMode, selectedUser, users])
    
    // Render add/edit view
    if (viewMode === 'add' || (viewMode === 'detail' && selectedUser)) {
        const currentUser = selectedUser ? users.find(u => u.id === selectedUser) : null
        const isEditing = !!currentUser
        
        return (
            <div className="h-full flex flex-col">
                {/* Header with Back Button */}
                <div className={cn(
                    "px-5 py-4 border-b",
                    isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
                )}>
                    <div className="flex items-center gap-3 mb-4">
                        <button
                            onClick={handleCancelUser}
                            className={cn(
                                "p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-white/5 transition-colors"
                            )}
                        >
                            <ChevronLeft className="w-4 h-4" />
                        </button>
                        <div>
                            <h2 className="text-lg font-semibold text-foreground">
                                {isEditing ? 'Edit User' : 'Invite New User'}
                            </h2>
                            <p className="text-xs text-muted-foreground">
                                {isEditing ? 'Update user information' : 'Invite a new user to your organization'}
                            </p>
                        </div>
                    </div>
                </div>
                
                {/* Form Content */}
                <div className="flex-1 overflow-y-auto p-5">
                    <div className="max-w-3xl mx-auto space-y-6">
                        {/* Name */}
                        <div>
                            <label className="text-sm font-medium text-foreground mb-2 block">
                                Name <span className="text-red-500">*</span>
                            </label>
                            <Input
                                value={formData.name}
                                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                placeholder="e.g., John Doe"
                                className={cn(
                                    "h-10 text-sm",
                                    isDark 
                                        ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                        : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                                )}
                            />
                        </div>
                        
                        {/* Email */}
                        <div>
                            <label className="text-sm font-medium text-foreground mb-2 block">
                                Email <span className="text-red-500">*</span>
                            </label>
                            <Input
                                type="email"
                                value={formData.email}
                                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                                placeholder="e.g., john.doe@example.com"
                                className={cn(
                                    "h-10 text-sm",
                                    isDark 
                                        ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                        : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                                )}
                            />
                        </div>
                        
                        {/* Status */}
                        <div>
                            <label className="text-sm font-medium text-foreground mb-2 block">
                                Status <span className="text-red-500">*</span>
                            </label>
                            <div className="relative">
                                <select
                                    value={formData.status}
                                    onChange={(e) => setFormData({ ...formData, status: e.target.value })}
                                    className={cn(
                                        "h-10 w-full px-3 pr-8 rounded-lg text-sm border appearance-none cursor-pointer",
                                        isDark 
                                            ? "bg-white/4 border-white/8 text-foreground" 
                                            : "bg-white border-black/8 text-foreground"
                                    )}
                                >
                                    <option value="active">Active</option>
                                    <option value="inactive">Inactive</option>
                                </select>
                                <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                            </div>
                        </div>
                        
                        {/* Crews Assignment - Only show when editing */}
                        {isEditing && (
                            <div>
                                <label className="text-sm font-medium text-foreground mb-2 block">
                                    Crews
                                </label>
                                <div className="space-y-3">
                                    {isLoadingCrews ? (
                                        <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
                                            <RefreshCw className="w-4 h-4 animate-spin" />
                                            Carregando crews...
                                        </div>
                                    ) : (
                                        <>
                                            {/* Current Crew Memberships */}
                                            {selectedUser && userCrewMemberships[selectedUser] && userCrewMemberships[selectedUser].length > 0 && (
                                                <div className="space-y-2">
                                                    {userCrewMemberships[selectedUser].map((membership) => {
                                                        const crew = crews.find(c => c.id === membership.crew_id)
                                                        const space = crew ? spaces.find(s => s.id === crew.space_id) : null
                                                        
                                                        // Role definitions with icons and colors
                                                        const roleOptions = [
                                                            { value: 'commander', label: 'Commander', icon: Settings, color: 'blue' },
                                                            { value: 'navigator', label: 'Navigator', icon: Navigation, color: 'green' },
                                                            { value: 'explorer', label: 'Explorer', icon: Compass, color: 'orange' },
                                                            { value: 'guest', label: 'Guest', icon: User, color: 'gray' },
                                                        ]
                                                        
                                                        const currentRole = roleOptions.find(r => r.value === membership.role) || roleOptions[2]
                                                        const RoleIcon = currentRole.icon
                                                        
                                                        return (
                                                            <div
                                                                key={membership.id}
                                                                className={cn(
                                                                    "p-3 rounded-lg border",
                                                                    "bg-white dark:bg-gray-800",
                                                                    "border-gray-200 dark:border-gray-700"
                                                                )}
                                                            >
                                                                <div className="flex items-center justify-between">
                                                                    <div className="flex items-center gap-3 flex-1">
                                                                        <div className={cn(
                                                                            "w-8 h-8 rounded-lg flex items-center justify-center text-white font-semibold text-xs",
                                                                            "bg-purple-500"
                                                                        )}>
                                                                            {crew?.name.charAt(0).toUpperCase() || 'C'}
                                                                        </div>
                                                                        <div className="flex-1">
                                                                            <p className="text-sm font-medium text-foreground">
                                                                                {crew?.name || 'Unknown Crew'}
                                                                            </p>
                                                                            <p className="text-xs text-muted-foreground">
                                                                                {space?.name || 'No space'}
                                                                            </p>
                                                                        </div>
                                                                    </div>
                                                                    
                                                                    {/* Role Selection */}
                                                                    <div className="flex items-center gap-2">
                                                                        <div className="relative">
                                                                            <select
                                                                                value={membership.role || 'explorer'}
                                                                                onChange={async (e) => {
                                                                                    const newRole = e.target.value
                                                                                    if (selectedUser && membership.crew_id && newRole !== membership.role) {
                                                                                        try {
                                                                                            await crewsApi.updateCrewMemberRole(membership.crew_id, selectedUser, newRole)
                                                                                            await loadUserCrewMemberships(selectedUser)
                                                                                        } catch (error) {
                                                                                            console.error('Error updating crew member role:', error)
                                                                                            alert(`Erro ao atualizar permissão: ${error instanceof Error ? error.message : 'Erro desconhecido'}`)
                                                                                        }
                                                                                    }
                                                                                }}
                                                                                className={cn(
                                                                                    "h-8 px-3 pr-8 rounded-lg text-xs border appearance-none cursor-pointer",
                                                                                    "flex items-center gap-2",
                                                                                    isDark 
                                                                                        ? "bg-white/4 border-white/8 text-foreground" 
                                                                                        : "bg-white border-black/8 text-foreground"
                                                                                )}
                                                                            >
                                                                                {roleOptions.map(role => (
                                                                                    <option key={role.value} value={role.value}>
                                                                                        {role.label}
                                                                                    </option>
                                                                                ))}
                                                                            </select>
                                                                            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-muted-foreground pointer-events-none" />
                                                                        </div>
                                                                        
                                                                        {/* Remove Button */}
                                                                        <button
                                                                            onClick={async () => {
                                                                                if (selectedUser && membership.crew_id) {
                                                                                    if (confirm(`Tem certeza que deseja remover este usuário da crew ${crew?.name}?`)) {
                                                                                        try {
                                                                                            await crewsApi.removeCrewMember(membership.crew_id, selectedUser)
                                                                                            await loadUserCrewMemberships(selectedUser)
                                                                                        } catch (error) {
                                                                                            console.error('Error removing crew member:', error)
                                                                                            alert(`Erro ao remover: ${error instanceof Error ? error.message : 'Erro desconhecido'}`)
                                                                                        }
                                                                                    }
                                                                                }
                                                                            }}
                                                                            className={cn(
                                                                                "px-3 py-1.5 rounded-lg text-xs font-medium",
                                                                                "text-red-600 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-900/20",
                                                                                "transition-colors"
                                                                            )}
                                                                        >
                                                                            Remover
                                                                        </button>
                                                                    </div>
                                                                </div>
                                                            </div>
                                                        )
                                                    })}
                                                </div>
                                            )}
                                            
                                            {/* Add Crew Dropdown */}
                                            <div className="relative">
                                                <select
                                                    onChange={async (e) => {
                                                        const crewId = e.target.value
                                                        if (crewId && selectedUser) {
                                                            try {
                                                                await crewsApi.addCrewMember(crewId, {
                                                                    user_id: selectedUser,
                                                                    role: 'explorer' // Default role
                                                                })
                                                                await loadUserCrewMemberships(selectedUser)
                                                                e.target.value = '' // Reset dropdown
                                                            } catch (error) {
                                                                console.error('Error adding crew member:', error)
                                                            }
                                                        }
                                                    }}
                                                    className={cn(
                                                        "h-10 w-full px-3 pr-8 rounded-lg text-sm border appearance-none cursor-pointer",
                                                        isDark 
                                                            ? "bg-white/4 border-white/8 text-foreground" 
                                                            : "bg-white border-black/8 text-foreground"
                                                    )}
                                                    defaultValue=""
                                                >
                                                    <option value="" disabled>
                                                        {selectedUser && userCrewMemberships[selectedUser]?.length > 0 
                                                            ? 'Adicionar outra crew...' 
                                                            : 'Selecione uma crew para adicionar...'}
                                                    </option>
                                                    {crews
                                                        .filter(crew => {
                                                            // Filter out crews user is already in
                                                            if (!selectedUser || !userCrewMemberships[selectedUser]) return true
                                                            return !userCrewMemberships[selectedUser].some(m => m.crew_id === crew.id)
                                                        })
                                                        .map(crew => {
                                                            const space = spaces.find(s => s.id === crew.space_id)
                                                            return (
                                                                <option key={crew.id} value={crew.id}>
                                                                    {crew.name} {space ? `(${space.name})` : ''}
                                                                </option>
                                                            )
                                                        })}
                                                </select>
                                                <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                                            </div>
                                        </>
                                    )}
                                </div>
                            </div>
                        )}
                        
                    </div>
                </div>
                
                {/* Actions */}
                <div className={cn(
                    "px-5 py-4 border-t",
                    isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
                )}>
                    <div className="max-w-3xl mx-auto flex items-center justify-end gap-3">
                        <button
                            onClick={handleCancelUser}
                            className={cn(
                                "px-4 py-2 rounded-lg text-sm font-medium",
                                "hover:bg-gray-100 dark:hover:bg-gray-700",
                                "transition-colors"
                            )}
                        >
                            Cancel
                        </button>
                        <button
                            onClick={() => {
                                setItemToDelete({ id: selectedUser!, name: formData.name })
                                setDeleteModalOpen(true)
                            }}
                            disabled={!isEditing}
                            className={cn(
                                "px-4 py-2 rounded-lg text-sm font-medium",
                                "bg-red-500 hover:bg-red-600 text-white",
                                "disabled:opacity-50 disabled:cursor-not-allowed",
                                "transition-colors"
                            )}
                        >
                            Delete
                        </button>
                        <button
                            onClick={handleSaveUser}
                            disabled={!formData.name || !formData.email}
                            className={cn(
                                "px-4 py-2 rounded-lg text-sm font-medium",
                                "bg-primary hover:bg-primary/90 text-primary-foreground",
                                "disabled:opacity-50 disabled:cursor-not-allowed",
                                "transition-colors"
                            )}
                        >
                            {isEditing ? 'Save Changes' : 'Invite User'}
                        </button>
                    </div>
                </div>
                
                {/* Delete Confirmation Modal */}
                <DeleteConfirmationModal
                    isOpen={deleteModalOpen}
                    onClose={() => {
                        setDeleteModalOpen(false)
                        setItemToDelete(null)
                    }}
                    onConfirm={async () => {
                        if (itemToDelete) {
                            try {
                                await usersApi.deleteUser(itemToDelete.id)
                            setUsers(users.filter(u => u.id !== itemToDelete.id))
                            setViewMode('list')
                            setSelectedUser(null)
                            } catch (error) {
                                console.error('Error deleting user:', error)
                            }
                        }
                    }}
                    itemName={itemToDelete?.name || ''}
                    itemType="user"
                    isDark={isDark}
                />
            </div>
        )
    }

    return (
        <div className="h-full flex flex-col">
            {/* Header Section */}
            <div className={cn(
                "px-5 py-4 border-b",
                isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
            )}>
                {/* Header Actions */}
                <div className="flex items-center justify-between mb-4">
                    <p className="text-xs text-muted-foreground flex-1">
                        Users are invited to the organisation. You can manage app access individually or via app access settings. <a href="#" className="text-blue-500 hover:underline">Go to app access settings</a>
                    </p>
                    <button
                        onClick={() => {
                            setViewMode('add')
                            setFormData({ name: '', email: '', status: 'active' })
                        }}
                        className={cn(
                            "px-4 py-2 rounded-lg text-sm font-medium flex items-center gap-2 transition-colors",
                            "bg-primary hover:bg-primary/90 text-primary-foreground"
                        )}
                    >
                        <UserPlus className="w-4 h-4" />
                        Invite users
                    </button>
                </div>

                {/* Stats Cards */}
                <div className="grid grid-cols-3 gap-4 mb-4">
                    <div className={cn(
                        "p-4 rounded-lg border",
                        "bg-white dark:bg-gray-800",
                        "border-gray-200 dark:border-gray-700"
                    )}>
                        <p className="text-xs text-muted-foreground mb-1">Total users</p>
                        <p className="text-2xl font-semibold text-foreground">{stats.total}</p>
                    </div>
                    <div className={cn(
                        "p-4 rounded-lg border",
                        "bg-white dark:bg-gray-800",
                        "border-gray-200 dark:border-gray-700"
                    )}>
                        <p className="text-xs text-muted-foreground mb-1">Active users</p>
                        <p className="text-2xl font-semibold text-foreground">{stats.active}</p>
                    </div>
                    <div className={cn(
                        "p-4 rounded-lg border",
                        "bg-white dark:bg-gray-800",
                        "border-gray-200 dark:border-gray-700"
                    )}>
                        <p className="text-xs text-muted-foreground mb-1">Organisation admins</p>
                        <p className="text-2xl font-semibold text-foreground">{stats.admins}</p>
                    </div>
                </div>

                {/* Search and Filters */}
                <div className="flex items-center gap-3 flex-wrap">
                    <div className="relative flex-1">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/50" />
                    <Input
                        type="text"
                        placeholder="Search by name or e..."
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
                <div className="relative">
                    <select
                        value={filterRole}
                        onChange={(e) => setFilterRole(e.target.value)}
                        className={cn(
                            "h-9 px-3 pr-8 rounded-lg text-xs border",
                            isDark 
                                ? "bg-white/4 border-white/8 text-foreground" 
                                : "bg-white border-black/8 text-foreground",
                            "appearance-none cursor-pointer"
                        )}
                    >
                        <option value="all">Role</option>
                        {uniqueRoles.map(role => (
                            <option key={role} value={role}>{role}</option>
                        ))}
                    </select>
                    <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                </div>
                <div className="relative">
                    <select
                        value={filterStatus}
                        onChange={(e) => setFilterStatus(e.target.value)}
                        className={cn(
                            "h-9 px-3 pr-8 rounded-lg text-xs border",
                            isDark 
                                ? "bg-white/4 border-white/8 text-foreground" 
                                : "bg-white border-black/8 text-foreground",
                            "appearance-none cursor-pointer"
                        )}
                    >
                        <option value="all">Status</option>
                        <option value="active">Active</option>
                        <option value="inactive">Inactive</option>
                    </select>
                    <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                </div>
                <div className="relative">
                    <select
                        value={filterSpace}
                        onChange={(e) => setFilterSpace(e.target.value)}
                        className={cn(
                            "h-9 px-3 pr-8 rounded-lg text-xs border",
                            isDark 
                                ? "bg-white/4 border-white/8 text-foreground" 
                                : "bg-white border-black/8 text-foreground",
                            "appearance-none cursor-pointer"
                        )}
                    >
                        <option value="all">Space</option>
                        {spaces.map(space => (
                            <option key={space.id} value={space.id}>{space.name}</option>
                        ))}
                    </select>
                    <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                </div>
                <div className="relative">
                    <select
                        value={filterCrew}
                        onChange={(e) => setFilterCrew(e.target.value)}
                        className={cn(
                            "h-9 px-3 pr-8 rounded-lg text-xs border",
                            isDark 
                                ? "bg-white/4 border-white/8 text-foreground" 
                                : "bg-white border-black/8 text-foreground",
                            "appearance-none cursor-pointer"
                        )}
                    >
                        <option value="all">Crew</option>
                        {crews.map(crew => (
                            <option key={crew.id} value={crew.id}>{crew.name}</option>
                        ))}
                    </select>
                    <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                    </div>
                </div>
            </div>

            {/* Content Area */}
            <div className="flex-1 overflow-y-auto p-5">
                {/* Users Cards - Professional Grid */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                    {paginatedUsers.map((user) => {
                        const userCrews = getUserCrews(user.id)
                        const userSpaces = getUserSpaces(user.id)

                        const initial = (user.name?.charAt(0) || "U").toUpperCase()
                        // Unified blue color scheme for all Data Catalog cards
                        const colorScheme = {
                            gradient: "from-blue-500/10 via-blue-400/5 to-blue-600/10",
                            border: "border-blue-500/20",
                            icon: "from-blue-500 to-blue-600",
                        }

                        const planetsCount = (user as any).planets || 0

                        return (
                            <div
                                key={user.id}
                                onClick={(e) => {
                                    if ((e.target as HTMLElement).closest("button")) return
                                    setSelectedUser(user.id)
                                    setViewMode("detail")
                                }}
                                className={cn(
                                    "group relative overflow-hidden cursor-pointer",
                                    "rounded-xl border transition-all duration-300",
                                        "bg-white/80 dark:bg-gray-800/80 backdrop-blur-sm",
                                    colorScheme.border,
                                    "hover:shadow-lg hover:shadow-blue-500/10 dark:hover:shadow-blue-500/20",
                                    "hover:scale-[1.02] hover:-translate-y-0.5"
                                )}
                            >
                                {/* Gradient background */}
                                <div
                                    className={cn(
                                        "absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300",
                                        `bg-gradient-to-br ${colorScheme.gradient}`
                                    )}
                                />

                                <div className="relative p-4">
                                    <div className="flex items-start gap-3 mb-3">
                                        {/* Avatar with gradient */}
                                        <div
                                            className={cn(
                                                "flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center",
                                                "bg-gradient-to-br shadow-lg",
                                                colorScheme.icon,
                                                "ring-2 ring-white/20 dark:ring-gray-700/50",
                                                "text-white font-bold text-sm"
                                            )}
                                        >
                                            {initial}
                                        </div>

                                        {/* Info */}
                                        <div className="flex-1 min-w-0 flex flex-col gap-1.5">
                                            <div className="flex items-center gap-2">
                                                <h3 className="font-semibold text-sm text-foreground truncate group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
                                                    {user.name}
                                                </h3>
                                                <span
                                                    className={cn(
                                                        "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium",
                                                        user.status === "active"
                                                            ? "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400"
                                                            : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"
                                                    )}
                                                >
                                                    {user.status === "active" && (
                                                        <CheckCircle2 className="w-3 h-3" />
                                                    )}
                                                    {user.status === "active" ? "Active" : "Inactive"}
                                                </span>
                                            </div>
                                            <p className="text-[11px] text-muted-foreground truncate">
                                                {user.email}
                                            </p>
                                        </div>
                                    </div>

                                    {/* Stats badges */}
                                    <TooltipProvider delayDuration={0}>
                                        <div className="flex items-center gap-1.5 flex-wrap">
                                            {/* Planets */}
                                            <Tooltip>
                                                <TooltipTrigger asChild>
                                                    <div
                                                        className={cn(
                                                            "flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] cursor-help",
                                                            "bg-gray-100/80 dark:bg-gray-700/50",
                                                            "backdrop-blur-sm border border-gray-200/50 dark:border-gray-600/50"
                                                        )}
                                                    >
                                                        <Globe className="w-2.5 h-2.5 text-muted-foreground" />
                                                        <span className="font-medium text-foreground">
                                                            {planetsCount}
                                                        </span>
                                                    </div>
                                                </TooltipTrigger>
                                                <TooltipContent side="top" className="text-xs">
                                                    {planetsCount === 1
                                                        ? "1 Planet"
                                                        : `${planetsCount} Planets`}
                                                </TooltipContent>
                                            </Tooltip>

                                            {/* Spaces */}
                                            <Tooltip>
                                                <TooltipTrigger asChild>
                                                    <div
                                                        className={cn(
                                                            "flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] cursor-help",
                                                            "bg-gray-100/80 dark:bg-gray-700/50",
                                                            "backdrop-blur-sm border border-gray-200/50 dark:border-gray-600/50"
                                                        )}
                                                    >
                                                        <Navigation className="w-2.5 h-2.5 text-muted-foreground" />
                                                        <span className="font-medium text-foreground">
                                                            {userSpaces.length}
                                                        </span>
                                                    </div>
                                                </TooltipTrigger>
                                                <TooltipContent side="top" className="text-xs">
                                                    {userSpaces.length === 1
                                                        ? "1 Space"
                                                        : `${userSpaces.length} Spaces`}
                                                </TooltipContent>
                                            </Tooltip>

                                            {/* Crews */}
                                            <Tooltip>
                                                <TooltipTrigger asChild>
                                                    <div
                                                        className={cn(
                                                            "flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] cursor-help",
                                                            "bg-gray-100/80 dark:bg-gray-700/50",
                                                            "backdrop-blur-sm border border-gray-200/50 dark:border-gray-600/50"
                                                        )}
                                                    >
                                                        <Users className="w-2.5 h-2.5 text-muted-foreground" />
                                                        <span className="font-medium text-foreground">
                                                            {userCrews.length}
                                                        </span>
                                                    </div>
                                                </TooltipTrigger>
                                                <TooltipContent side="top" className="text-xs">
                                                    {userCrews.length === 1
                                                        ? "1 Crew"
                                                        : `${userCrews.length} Crews`}
                                                </TooltipContent>
                                            </Tooltip>
                                        </div>
                                    </TooltipProvider>
                                </div>
                            </div>
                        )
                    })}
                </div>
                
                {/* Delete Confirmation Modal */}
                <DeleteConfirmationModal
                    isOpen={deleteModalOpen}
                    onClose={() => {
                        setDeleteModalOpen(false)
                        setItemToDelete(null)
                    }}
                    onConfirm={async () => {
                        if (itemToDelete) {
                            try {
                                await usersApi.deleteUser(itemToDelete.id)
                            setUsers(users.filter(u => u.id !== itemToDelete.id))
                            } catch (error) {
                                console.error('Error deleting user:', error)
                            }
                        }
                    }}
                    itemName={itemToDelete?.name || ''}
                    itemType="user"
                    isDark={isDark}
                />

                {/* Pagination */}
                <div className="flex items-center justify-between mt-5">
                    <div className="text-xs text-muted-foreground">
                        {((currentPage - 1) * itemsPerPage) + 1} to {Math.min(currentPage * itemsPerPage, filteredUsers.length)} of {filteredUsers.length}
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                            disabled={currentPage === 1}
                            className={cn(
                                "px-3 py-1.5 rounded text-sm",
                                "hover:bg-gray-100 dark:hover:bg-gray-700",
                                "disabled:opacity-50 disabled:cursor-not-allowed",
                                "transition-colors"
                            )}
                        >
                            <ChevronLeft className="w-4 h-4" />
                        </button>
                        <span className="text-xs text-muted-foreground">Previous</span>
                        <span className="text-xs text-muted-foreground">Next</span>
                        <button
                            onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                            disabled={currentPage === totalPages}
                            className={cn(
                                "px-3 py-1.5 rounded text-sm",
                                "hover:bg-gray-100 dark:hover:bg-gray-700",
                                "disabled:opacity-50 disabled:cursor-not-allowed",
                                "transition-colors"
                            )}
                        >
                            <ChevronRight className="w-4 h-4" />
                        </button>
                        <div className="relative ml-2">
                            <select
                                value={itemsPerPage}
                                onChange={(e) => {
                                    const value = Number(e.target.value)
                                    setItemsPerPage(value)
                                    setCurrentPage(1)
                                }}
                                className={cn(
                                    "h-8 px-2 pr-6 rounded text-xs border",
                                    isDark 
                                        ? "bg-white/4 border-white/8 text-foreground" 
                                        : "bg-white border-black/8 text-foreground",
                                    "appearance-none cursor-pointer"
                                )}
                            >
                                <option value="10">10</option>
                                <option value="20">20</option>
                                <option value="50">50</option>
                                <option value="100">100</option>
                            </select>
                            <ChevronDown className="absolute right-1 top-1/2 -translate-y-1/2 w-3 h-3 text-muted-foreground pointer-events-none" />
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}

// ============================================
// TABLE PERMISSIONS MODAL COMPONENT
// ============================================
interface TablePermissionsModalProps {
    isOpen: boolean
    onClose: () => void
    connectionId: string
    tableName: string
    spaceId: string
    spaceCrews: ApiCrew[]
    crewMembers: Record<string, ApiCrewMember[]>
    permissions: TableMemberPermission[]
    isDark: boolean
}

function TablePermissionsModal({
    isOpen,
    onClose,
    connectionId,
    tableName,
    spaceId,
    spaceCrews,
    crewMembers,
    permissions,
    isDark
}: TablePermissionsModalProps) {
    const [isSubmitting, setIsSubmitting] = useState(false)
    
    // Group permissions by crew
    const permissionsByCrew = spaceCrews.reduce((acc, crew) => {
        const members = crewMembers[crew.id] || []
        acc[crew.id] = members.map(member => {
            const perm = permissions.find(p => p.member_id === member.id)
            return {
                member,
                permission: perm,
                hasAccess: perm ? perm.has_access === "true" : true // Default to true if no permission set
            }
        })
        return acc
    }, {} as Record<string, Array<{ member: ApiCrewMember; permission?: TableMemberPermission; hasAccess: boolean }>>)
    
    const toggleMemberAccess = async (crewId: string, memberId: string, currentAccess: boolean) => {
        setIsSubmitting(true)
        try {
            const existingPerm = permissions.find(p => p.member_id === memberId)
            const newAccess = !currentAccess
            
            if (existingPerm) {
                // Update existing permission
                await permissionsApi.updateTableMemberPermission(existingPerm.id, {
                    has_access: newAccess ? "true" : "false"
                })
            } else {
                // Create new permission
                await permissionsApi.createTableMemberPermission({
                    connection_id: connectionId,
                    table_name: tableName,
                    crew_id: crewId,
                    member_id: memberId,
                    has_access: newAccess ? "true" : "false"
                })
            }
            
            // Reload permissions
            const updatedPermissions = await permissionsApi.getTableMemberPermissions(connectionId, tableName)
            // Update parent state would be handled by parent component
            onClose()
        } catch (error) {
            console.error('Error updating table member permission:', error)
            alert(`Error: ${error instanceof Error ? error.message : 'Unknown error'}`)
        } finally {
            setIsSubmitting(false)
        }
    }
    
    if (!isOpen) return null
    
    return (
        <>
            <div 
                className="fixed inset-0 z-50 bg-black/50" 
                onClick={onClose}
            />
            <div className={cn(
                "fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2",
                "w-full max-w-2xl max-h-[80vh] rounded-lg border shadow-lg",
                "bg-white dark:bg-gray-800",
                "border-gray-200 dark:border-gray-700",
                "flex flex-col"
            )}>
                <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-gray-700">
                    <div>
                        <h3 className="text-lg font-semibold text-foreground">Permissões da Tabela</h3>
                        <p className="text-sm text-muted-foreground mt-1">{tableName}</p>
                    </div>
                    <button
                        onClick={onClose}
                        className={cn(
                            "p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-white/5",
                            "transition-colors"
                        )}
                    >
                        <X className="w-4 h-4" />
                    </button>
                </div>
                
                <div className="flex-1 overflow-y-auto p-6">
                    <div className="space-y-6">
                        {Object.entries(permissionsByCrew).map(([crewId, members]) => {
                            const crew = spaceCrews.find(c => c.id === crewId)
                            if (!crew) return null
                            
                            return (
                                <div key={crewId} className="space-y-2">
                                    <h4 className="text-sm font-semibold text-foreground">{crew.name}</h4>
                                    <div className="space-y-2">
                                        {members.map(({ member, permission, hasAccess }) => (
                                            <div
                                                key={member.id}
                                                className={cn(
                                                    "flex items-center justify-between p-3 rounded-lg border",
                                                    "bg-gray-50 dark:bg-gray-900/50",
                                                    "border-gray-200 dark:border-gray-700"
                                                )}
                                            >
                                                <div className="flex items-center gap-3">
                                                    <div className={cn(
                                                        "w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold",
                                                        hasAccess 
                                                            ? "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400"
                                                            : "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400"
                                                    )}>
                                                        {hasAccess ? "✓" : "✗"}
                                                    </div>
                                                    <div>
                                                        <p className="text-sm font-medium text-foreground">
                                                            {member.user?.name || member.user?.email || `Member ${member.user_id.slice(0, 8)}`}
                                                        </p>
                                                        <p className="text-xs text-muted-foreground">
                                                            {hasAccess ? "Tem acesso" : "Sem acesso"}
                                                        </p>
                                                    </div>
                                                </div>
                                                <button
                                                    onClick={() => toggleMemberAccess(crewId, member.id, hasAccess)}
                                                    disabled={isSubmitting}
                                                    className={cn(
                                                        "px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                                                        hasAccess
                                                            ? "bg-red-500 hover:bg-red-600 text-white"
                                                            : "bg-green-500 hover:bg-green-600 text-white",
                                                        "disabled:opacity-50 disabled:cursor-not-allowed"
                                                    )}
                                                >
                                                    {hasAccess ? "Remover Acesso" : "Dar Acesso"}
                                                </button>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                </div>
            </div>
        </>
    )
}

// ============================================
// SPACES SECTION - Separate Section
// ============================================
export function SpacesSection({ isDark }: { isDark: boolean }) {
    // Use real stores
    const { spaces, fetchSpaces, spaceCrews, fetchSpaceCrews } = useSpaceStore()
    const { crews, fetchCrews, crewMembers, fetchCrewMembers } = useCrewStore()
    
    // State for tables and permissions
    const [spaceTables, setSpaceTables] = useState<Record<string, SpaceTable[]>>({})
    const [tablePermissions, setTablePermissions] = useState<Record<string, TableMemberPermission[]>>({})
    const [selectedTable, setSelectedTable] = useState<{ connectionId: string; tableName: string } | null>(null)
    const [isLoadingTables, setIsLoadingTables] = useState(false)
    const [searchQuery, setSearchQuery] = useState('')
    const [selectedSpace, setSelectedSpace] = useState<string | null>(null)
    const [viewMode, setViewMode] = useState<'list' | 'detail' | 'add'>('list')
    const [deleteModalOpen, setDeleteModalOpen] = useState(false)
    const [itemToDelete, setItemToDelete] = useState<{ id: string; name: string } | null>(null)
    const [currentPage, setCurrentPage] = useState(1)
    const [itemsPerPage, setItemsPerPage] = useState(10)
    const [formData, setFormData] = useState({ name: '', description: '', color: 'blue' })
    
    // State for crew table assignment
    const [addCrewDropdownOpen, setAddCrewDropdownOpen] = useState(false)
    const [selectedCrewForTables, setSelectedCrewForTables] = useState<string | null>(null)
    const [assignmentMode, setAssignmentMode] = useState<'none' | 'all' | 'manual'>('none')
    const [selectedTablesForAssignment, setSelectedTablesForAssignment] = useState<Set<string>>(new Set())
    const [isSubmittingAssignment, setIsSubmittingAssignment] = useState(false)
    
    // Load spaces and crews on mount
    useEffect(() => {
        fetchSpaces().catch(console.error)
        fetchCrews().catch(console.error)
    }, [fetchSpaces, fetchCrews])
    
    // Load crews for each space when spaces are loaded
    useEffect(() => {
        spaces.forEach(space => {
            if (!spaceCrews[space.id]) {
                fetchSpaceCrews(space.id).catch(console.error)
            }
        })
    }, [spaces, spaceCrews, fetchSpaceCrews])
    
    // Load crew members when space crews are loaded
    useEffect(() => {
        if (selectedSpace && spaceCrews[selectedSpace]) {
            spaceCrews[selectedSpace].forEach(crew => {
                if (!crewMembers[crew.id]) {
                    fetchCrewMembers(crew.id).catch(console.error)
                }
            })
        }
    }, [selectedSpace, spaceCrews, crewMembers, fetchCrewMembers])
    
    // Load crews for selected space when entering detail view
    useEffect(() => {
        if (selectedSpace && viewMode === 'detail') {
            // Always reload crews when entering detail view to ensure we have the latest data
            console.log(`Loading crews for space ${selectedSpace}`)
            fetchSpaceCrews(selectedSpace)
                .then(() => {
                    const crews = spaceCrews[selectedSpace] || []
                    console.log(`Loaded ${crews.length} crews for space ${selectedSpace}:`, crews)
                })
                .catch(error => {
                    console.error(`Error loading crews for space ${selectedSpace}:`, error)
                })
        }
    }, [selectedSpace, viewMode, fetchSpaceCrews, spaceCrews])
    
    // Load tables when a space is selected in detail view
    useEffect(() => {
        if (selectedSpace && viewMode === 'detail') {
            loadSpaceTables(selectedSpace)
            // Reset assignment state when space changes
            setSelectedCrewForTables(null)
            setAssignmentMode('none')
            setSelectedTablesForAssignment(new Set())
            setAddCrewDropdownOpen(false)
        }
    }, [selectedSpace, viewMode])
    
    // Load permissions for all tables when tables are loaded
    useEffect(() => {
        if (selectedSpace && spaceTables[selectedSpace] && spaceTables[selectedSpace].length > 0) {
            spaceTables[selectedSpace].forEach(table => {
                const key = `${table.connection_id}:${table.table_name}`
                if (!tablePermissions[key] || tablePermissions[key].length === 0) {
                    loadTablePermissions(table.connection_id, table.table_name).catch(console.error)
                }
            })
        }
    }, [selectedSpace, spaceTables])
    
    // Load permissions when a table is selected (for modal)
    useEffect(() => {
        if (selectedTable) {
            loadTablePermissions(selectedTable.connectionId, selectedTable.tableName)
        }
    }, [selectedTable])
    
    const loadSpaceTables = async (spaceId: string) => {
        setIsLoadingTables(true)
        try {
            const tables = await spacesApi.getSpaceTables(spaceId)
            setSpaceTables(prev => ({ ...prev, [spaceId]: tables }))
        } catch (error) {
            console.error('Error loading space tables:', error)
        } finally {
            setIsLoadingTables(false)
        }
    }
    
    const loadTablePermissions = async (connectionId: string, tableName: string) => {
        try {
            const permissions = await permissionsApi.getTableMemberPermissions(connectionId, tableName)
            const key = `${connectionId}:${tableName}`
            setTablePermissions(prev => ({ ...prev, [key]: permissions }))
        } catch (error) {
            console.error('Error loading table permissions:', error)
        }
    }
    
    // Get crews that have access to a table (based on member permissions)
    const getCrewsWithAccess = (connectionId: string, tableName: string): string[] => {
        const key = `${connectionId}:${tableName}`
        const permissions = tablePermissions[key] || []
        
        // Get unique crew IDs from permissions where has_access is "true"
        const crewIdsWithAccess = new Set<string>()
        permissions.forEach(perm => {
            if (perm.has_access === "true") {
                crewIdsWithAccess.add(perm.crew_id)
            }
        })
        
        return Array.from(crewIdsWithAccess)
    }
    
    // Add crew access to a table (grant access to all members)
    const addCrewToTable = async (connectionId: string, tableName: string, crewId: string) => {
        try {
            // Ensure crew members are loaded
            if (!crewMembers[crewId] || crewMembers[crewId].length === 0) {
                await fetchCrewMembers(crewId)
            }
            
            const members = crewMembers[crewId] || []
            
            if (members.length === 0) {
                console.warn(`Crew ${crewId} has no members`)
                return
            }
            
            // Load existing permissions first to check what already exists
            const key = `${connectionId}:${tableName}`
            const existingPerms = tablePermissions[key] || []
            const existingMemberIds = new Set(existingPerms.map(p => p.member_id))
            
            // Create permissions for all members of the crew
            const errors: string[] = []
            for (const member of members) {
                try {
                    // Check if permission already exists
                    const existingPerm = existingPerms.find(p => p.member_id === member.id && p.crew_id === crewId)
                    
                    if (existingPerm) {
                        // Update existing permission if it's not already "true"
                        if (existingPerm.has_access !== "true") {
                            await permissionsApi.updateTableMemberPermission(existingPerm.id, {
                                has_access: "true"
                            })
                        }
                    } else {
                        // Create new permission
                        await permissionsApi.createTableMemberPermission({
                            connection_id: connectionId,
                            table_name: tableName,
                            crew_id: crewId,
                            member_id: member.id,
                            has_access: "true"
                        })
                    }
                } catch (error: any) {
                    // If permission already exists (race condition), try to update
                    if (error?.message?.includes('already exists') || error?.message?.includes('Permission')) {
                        try {
                            // Reload permissions and try to update
                            const updatedPerms = await permissionsApi.getTableMemberPermissions(connectionId, tableName)
                            const perm = updatedPerms.find(p => p.member_id === member.id && p.crew_id === crewId)
                            if (perm && perm.has_access !== "true") {
                                await permissionsApi.updateTableMemberPermission(perm.id, {
                                    has_access: "true"
                                })
                            }
                        } catch (updateError) {
                            console.error(`Error updating permission for member ${member.id}:`, updateError)
                            errors.push(`Member ${member.id}: ${updateError instanceof Error ? updateError.message : 'Unknown error'}`)
                        }
                    } else {
                        console.error(`Error creating permission for member ${member.id}:`, error)
                        errors.push(`Member ${member.id}: ${error instanceof Error ? error.message : 'Unknown error'}`)
                    }
                }
            }
            
            // Reload permissions after all operations
            await loadTablePermissions(connectionId, tableName)
            
            if (errors.length > 0) {
                console.warn('Some permissions failed:', errors)
                // Don't show alert for partial failures, just log
            }
        } catch (error) {
            console.error('Error adding crew to table:', error)
            throw error // Re-throw to let caller handle
        }
    }
    
    // Remove crew access from a table (remove access from all members)
    const removeCrewFromTable = async (connectionId: string, tableName: string, crewId: string) => {
        try {
            const key = `${connectionId}:${tableName}`
            const permissions = tablePermissions[key] || []
            
            // Find all permissions for members of this crew
            const members = crewMembers[crewId] || []
            const memberIds = new Set(members.map(m => m.id))
            
            // Remove or update permissions for all members
            for (const perm of permissions) {
                if (memberIds.has(perm.member_id) && perm.crew_id === crewId) {
                    if (perm.has_access === "true") {
                        // Update to remove access
                        await permissionsApi.updateTableMemberPermission(perm.id, {
                            has_access: "false"
                        })
                    }
                }
            }
            
            // Reload permissions
            await loadTablePermissions(connectionId, tableName)
        } catch (error) {
            console.error('Error removing crew from table:', error)
            alert(`Erro ao remover crew da tabela: ${error instanceof Error ? error.message : 'Erro desconhecido'}`)
        }
    }
    
    // Handle crew selection for table assignment
    const handleSelectCrewForAssignment = (crewId: string) => {
        setSelectedCrewForTables(crewId)
        setAddCrewDropdownOpen(false)
        setAssignmentMode('none') // Reset to show options
        setSelectedTablesForAssignment(new Set())
    }
    
    // Handle "Add all tables" option
    const handleAddAllTables = async () => {
        if (!selectedCrewForTables || !selectedSpace) return
        
        setIsSubmittingAssignment(true)
        try {
            const tables = spaceTables[selectedSpace] || []
            
            if (tables.length === 0) {
                alert('Nenhuma tabela disponível para adicionar.')
                setIsSubmittingAssignment(false)
                return
            }
            
            // Add crew to all tables (with error handling per table)
            const errors: string[] = []
            for (const table of tables) {
                try {
                    await addCrewToTable(table.connection_id, table.table_name, selectedCrewForTables)
                } catch (error) {
                    console.error(`Error adding table ${table.table_name}:`, error)
                    errors.push(`${table.table_name}: ${error instanceof Error ? error.message : 'Erro desconhecido'}`)
                }
            }
            
            // Reset state
            setSelectedCrewForTables(null)
            setAssignmentMode('none')
            setSelectedTablesForAssignment(new Set())
            
            if (errors.length > 0) {
                alert(`Algumas tabelas foram adicionadas, mas houve erros:\n${errors.slice(0, 5).join('\n')}${errors.length > 5 ? `\n... e mais ${errors.length - 5} erros` : ''}`)
            } else {
                alert('Todas as tabelas foram adicionadas à crew com sucesso!')
            }
        } catch (error) {
            console.error('Error adding all tables:', error)
            alert(`Erro ao adicionar tabelas: ${error instanceof Error ? error.message : 'Erro desconhecido'}`)
        } finally {
            setIsSubmittingAssignment(false)
        }
    }
    
    // Handle "Add manually" option
    const handleStartManualAssignment = () => {
        setAssignmentMode('manual')
        setSelectedTablesForAssignment(new Set())
    }
    
    // Toggle table selection in manual mode
    const toggleTableSelection = (connectionId: string, tableName: string) => {
        if (assignmentMode !== 'manual') return
        
        const key = `${connectionId}:${tableName}`
        setSelectedTablesForAssignment(prev => {
            const newSet = new Set(prev)
            if (newSet.has(key)) {
                newSet.delete(key)
            } else {
                newSet.add(key)
            }
            return newSet
        })
    }
    
    // Confirm manual assignment
    const handleConfirmManualAssignment = async () => {
        if (!selectedCrewForTables || selectedTablesForAssignment.size === 0) {
            alert('Selecione pelo menos uma tabela')
            return
        }
        
        const tablesCount = selectedTablesForAssignment.size
        setIsSubmittingAssignment(true)
        try {
            // Add crew to selected tables (with error handling per table)
            const errors: string[] = []
            for (const key of selectedTablesForAssignment) {
                try {
                    const [connectionId, tableName] = key.split(':')
                    await addCrewToTable(connectionId, tableName, selectedCrewForTables)
                } catch (error) {
                    console.error(`Error adding table ${key}:`, error)
                    errors.push(`${key.split(':')[1]}: ${error instanceof Error ? error.message : 'Erro desconhecido'}`)
                }
            }
            
            // Reset state
            setSelectedCrewForTables(null)
            setAssignmentMode('none')
            setSelectedTablesForAssignment(new Set())
            
            if (errors.length > 0) {
                alert(`Algumas tabelas foram adicionadas, mas houve erros:\n${errors.slice(0, 5).join('\n')}${errors.length > 5 ? `\n... e mais ${errors.length - 5} erros` : ''}`)
            } else {
                alert(`${tablesCount} tabela(s) foram adicionadas à crew com sucesso!`)
            }
        } catch (error) {
            console.error('Error confirming manual assignment:', error)
            alert(`Erro ao adicionar tabelas: ${error instanceof Error ? error.message : 'Erro desconhecido'}`)
        } finally {
            setIsSubmittingAssignment(false)
        }
    }
    
    // Cancel assignment mode
    const handleCancelAssignment = () => {
        setSelectedCrewForTables(null)
        setAssignmentMode('none')
        setSelectedTablesForAssignment(new Set())
        setAddCrewDropdownOpen(false)
    }
    
    const filteredSpaces = spaces.filter(space => 
        space.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        space.description?.toLowerCase().includes(searchQuery.toLowerCase())
    )
    
    const paginatedSpaces = filteredSpaces.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage)
    const totalPages = Math.ceil(filteredSpaces.length / itemsPerPage)
    
    const getSpaceStats = (spaceId: string) => {
        const spaceCrewsList = spaceCrews[spaceId] || []
        const allMembers = new Set<string>()
        spaceCrewsList.forEach(crew => {
            const members = crewMembers[crew.id] || []
            members.forEach(member => allMembers.add(member.user_id))
        })
        const tables = spaceTables[spaceId] || []
        const uniqueConnections = new Set(tables.map(t => t.connection_id))
        return {
            crews: spaceCrewsList.length,
            members: allMembers.size,
            connections: uniqueConnections.size,
            tables: tables.length
        }
    }
    
    const stats = {
        total: spaces.length,
        totalCrews: crews.length,
        totalMembers: new Set(
            Object.values(crewMembers).flatMap(members => members.map(m => m.user_id))
        ).size,
    }
    
    const handleSaveSpace = async () => {
        try {
        if (selectedSpace) {
            // Update existing
                const { updateSpace } = useSpaceStore.getState()
                await updateSpace(selectedSpace, {
                        name: formData.name,
                    description: formData.description || ''
                })
                await fetchSpaces()
        } else {
            // Create new
                const { createSpace } = useSpaceStore.getState()
                await createSpace({
                name: formData.name,
                    description: formData.description || ''
                })
                await fetchSpaces()
            }
        } catch (error) {
            console.error('Error saving space:', error)
            return
        }
        
        // Reset
        setViewMode('list')
        setSelectedSpace(null)
        setFormData({ name: '', description: '', color: 'blue' })
    }
    
    const handleCancelSpace = () => {
        setViewMode('list')
        setSelectedSpace(null)
        setFormData({ name: '', description: '', color: 'blue' })
    }
    
    // Initialize form data when adding new space
    useEffect(() => {
        if (viewMode === 'add') {
            setFormData({ name: '', description: '', color: 'blue' })
        }
    }, [viewMode])
    
    // Render detail view - show tables when space is selected
    if (viewMode === 'detail' && selectedSpace) {
        const currentSpace = spaces.find(s => s.id === selectedSpace)
        if (!currentSpace) {
            setViewMode('list')
            setSelectedSpace(null)
            return null
        }
        
        return (
            <div className="h-full flex flex-col">
                {/* Header with Back Button */}
                <div className={cn(
                    "px-5 py-4 border-b",
                    isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
                )}>
                    <div className="flex items-center gap-3">
                        <button
                            onClick={() => {
                                setViewMode('list')
                                setSelectedSpace(null)
                                setSelectedTable(null)
                            }}
                            className={cn(
                                "p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-white/5 transition-colors"
                            )}
                        >
                            <ChevronLeft className="w-4 h-4" />
                        </button>
                        <div className="flex items-center gap-3">
                            <div className={cn(
                                "w-10 h-10 rounded-lg flex items-center justify-center text-white font-bold",
                                "bg-blue-500" // Default color since Space API doesn't have color field
                            )}>
                                {currentSpace.name.charAt(0).toUpperCase()}
                            </div>
                            <div>
                                <h2 className="text-lg font-semibold text-foreground">{currentSpace.name}</h2>
                                <p className="text-xs text-muted-foreground">
                                    {currentSpace.description || 'Space'}
                                </p>
                            </div>
                        </div>
                    </div>
                </div>
                
                {/* Tables Content */}
                <div className="flex-1 overflow-y-auto p-5">
                    <div className="max-w-4xl mx-auto">
                        <div className="flex items-center justify-between mb-4">
                            <div>
                                <h3 className="text-sm font-semibold text-foreground">Tabelas Conectadas</h3>
                                <p className="text-xs text-muted-foreground mt-1">
                                    Visualize todas as tabelas disponíveis nas conexões deste space
                                </p>
                            </div>
                            <div className="flex items-center gap-2">
                                {/* Add Crew Button with Dropdown */}
                                <div className="relative">
                                    <button
                                        onClick={() => {
                                            if (assignmentMode === 'none' && !selectedCrewForTables) {
                                                setAddCrewDropdownOpen(!addCrewDropdownOpen)
                                            } else {
                                                handleCancelAssignment()
                                            }
                                        }}
                                        disabled={isLoadingTables || (spaceCrews[selectedSpace] || []).length === 0}
                                        className={cn(
                                            "px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-2",
                                            assignmentMode !== 'none' || selectedCrewForTables
                                                ? "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50"
                        : "bg-primary hover:bg-primary/90 text-primary-foreground",
                                            "disabled:opacity-50 disabled:cursor-not-allowed",
                                            "transition-colors"
                                        )}
                                    >
                                        {assignmentMode !== 'none' || selectedCrewForTables ? (
                                            <>
                                                <X className="w-3 h-3" />
                                                Cancelar
                                            </>
                                        ) : (
                                            <>
                                                <UserPlus className="w-3 h-3" />
                                                Add Crew
                                            </>
                                        )}
                                    </button>
                                    
                                    {/* Dropdown Menu */}
                                    {addCrewDropdownOpen && assignmentMode === 'none' && !selectedCrewForTables && selectedSpace && (
                                        <>
                                            <div 
                                                className="fixed inset-0 z-40" 
                                                onClick={() => setAddCrewDropdownOpen(false)}
                                            />
                                            <div className={cn(
                                                "absolute right-0 top-full mt-1 z-50 min-w-[200px] rounded-lg border shadow-lg",
                                                "bg-white dark:bg-gray-800",
                                                "border-gray-200 dark:border-gray-700",
                                                "py-1 max-h-[300px] overflow-y-auto"
                                            )}>
                                                {(() => {
                                                    const crews = spaceCrews[selectedSpace]
                                                    console.log(`[Add Crew Dropdown] Space: ${selectedSpace}, Crews:`, crews)
                                                    
                                                    if (!crews) {
                                                        return (
                                                            <div className="px-3 py-2 text-xs text-muted-foreground text-center">
                                                                Carregando crews...
                                                            </div>
                                                        )
                                                    }
                                                    
                                                    if (crews.length === 0) {
                                                        return (
                                                            <div className="px-3 py-2 text-xs text-muted-foreground text-center">
                                                                Nenhuma crew disponível neste space
                                                            </div>
                                                        )
                                                    }
                                                    
                                                    return crews.map(crew => (
                                                        <button
                                                            key={crew.id}
                                                            onClick={() => {
                                                                console.log(`[Add Crew] Selected crew: ${crew.name} (${crew.id})`)
                                                                handleSelectCrewForAssignment(crew.id)
                                                            }}
                                                            className={cn(
                                                                "w-full px-3 py-2 text-left text-xs hover:bg-gray-100 dark:hover:bg-gray-700",
                                                                "transition-colors"
                                                            )}
                                                        >
                                                            {crew.name}
                                                        </button>
                                                    ))
                                                })()}
                                            </div>
                                        </>
                                    )}
                                    
                                    {/* Options after crew selection */}
                                    {selectedCrewForTables && assignmentMode === 'none' && (
                                        <>
                                            <div 
                                                className="fixed inset-0 z-40" 
                                                onClick={handleCancelAssignment}
                                            />
                                            <div className={cn(
                                                "absolute right-0 top-full mt-1 z-50 min-w-[200px] rounded-lg border shadow-lg",
                                                "bg-white dark:bg-gray-800",
                                                "border-gray-200 dark:border-gray-700",
                                                "py-1"
                                            )}>
                                                <button
                                                    onClick={handleAddAllTables}
                                                    disabled={isSubmittingAssignment}
                                                    className={cn(
                                                        "w-full px-3 py-2 text-left text-xs hover:bg-gray-100 dark:hover:bg-gray-700",
                                                        "transition-colors disabled:opacity-50"
                                                    )}
                                                >
                                                    Add all tables
                                                </button>
                                                <button
                                                    onClick={handleStartManualAssignment}
                                                    className={cn(
                                                        "w-full px-3 py-2 text-left text-xs hover:bg-gray-100 dark:hover:bg-gray-700",
                                                        "transition-colors"
                                                    )}
                                                >
                                                    Add manually
                                                </button>
                                            </div>
                                        </>
                                    )}
                                </div>
                                
                                <button
                                    onClick={() => loadSpaceTables(selectedSpace)}
                                    disabled={isLoadingTables}
                                    className={cn(
                                        "px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-2",
                                        "bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600",
                                        "disabled:opacity-50 disabled:cursor-not-allowed",
                                        "transition-colors"
                                    )}
                                >
                                    <RefreshCw className={cn("w-3 h-3", isLoadingTables && "animate-spin")} />
                                    Atualizar
                                </button>
                            </div>
                        </div>
                        
                        {/* Manual Assignment Mode Info */}
                        {assignmentMode === 'manual' && selectedCrewForTables && (
                            <div className={cn(
                                "mb-4 p-3 rounded-lg border",
                                "bg-blue-50 dark:bg-blue-900/20",
                                "border-blue-200 dark:border-blue-800"
                            )}>
                                <div className="flex items-center justify-between">
                                    <div>
                                        <p className="text-xs font-medium text-blue-900 dark:text-blue-100">
                                            Modo de seleção manual
                                        </p>
                                        <p className="text-xs text-blue-700 dark:text-blue-300 mt-1">
                                            Clique nas tabelas para selecioná-las. {selectedTablesForAssignment.size} tabela(s) selecionada(s).
                                        </p>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <button
                                            onClick={handleCancelAssignment}
                                            className={cn(
                                                "px-3 py-1.5 rounded-lg text-xs font-medium",
                                                "bg-white dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600",
                                                "transition-colors"
                                            )}
                                        >
                                            Cancelar
                                        </button>
                                        <button
                                            onClick={handleConfirmManualAssignment}
                                            disabled={selectedTablesForAssignment.size === 0 || isSubmittingAssignment}
                                            className={cn(
                                                "px-3 py-1.5 rounded-lg text-xs font-medium",
                                                "bg-primary hover:bg-primary/90 text-primary-foreground",
                                                "disabled:opacity-50 disabled:cursor-not-allowed",
                                                "transition-colors"
                                            )}
                                        >
                                            {isSubmittingAssignment ? 'Salvando...' : `Confirmar (${selectedTablesForAssignment.size})`}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        )}
                        {isLoadingTables ? (
                            <div className="flex items-center gap-2 text-sm text-muted-foreground py-8">
                                <RefreshCw className="w-4 h-4 animate-spin" />
                                Carregando tabelas...
                            </div>
                        ) : spaceTables[selectedSpace]?.length > 0 ? (
                            <div className="space-y-4">
                                {Object.values(
                                    (spaceTables[selectedSpace] || []).reduce((acc, table) => {
                                        const key = table.connection_id
                                        if (!acc[key]) {
                                            acc[key] = {
                                                connectionId: table.connection_id,
                                                connectionName: table.connection_name,
                                                connectionType: table.connection_type || 'database',
                                                tables: [] as typeof spaceTables[string],
                                            }
                                        }
                                        acc[key].tables.push(table)
                                        return acc
                                    }, {} as Record<string, { connectionId: string; connectionName: string; connectionType: string; tables: typeof spaceTables[string] }>)
                                ).map((conn) => (
                                    <div
                                        key={conn.connectionId}
                                        className={cn(
                                            "rounded-xl border",
                                            "bg-white dark:bg-gray-900/40",
                                            "border-gray-200 dark:border-gray-800"
                                        )}
                                    >
                                        {/* Connection header */}
                                        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-800">
                                            <div className="flex items-center gap-3">
                                                <div className={cn(
                                                    "w-9 h-9 rounded-lg flex items-center justify-center",
                                                    "bg-gray-100 dark:bg-gray-800"
                                                )}>
                                                    <Database className="w-4 h-4 text-muted-foreground" />
                                                </div>
                                                <div>
                                                    <p className="text-sm font-semibold text-foreground">
                                                        {conn.connectionName}
                                                    </p>
                                                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                                                        {conn.connectionType}
                                                    </p>
                                                </div>
                                            </div>
                                            <span className="text-[11px] text-muted-foreground">
                                                {conn.tables.length} tabela{conn.tables.length !== 1 && 's'}
                                            </span>
                                        </div>

                                        {/* Tables for this connection */}
                                        <div className="p-3 space-y-2">
                                            {conn.tables.map((table) => {
                                                const crewsWithAccess = getCrewsWithAccess(table.connection_id, table.table_name)
                                                const tableKey = `${table.connection_id}:${table.table_name}`
                                                const isSelected = assignmentMode === 'manual' && selectedTablesForAssignment.has(tableKey)
                                                
                                                return (
                                                    <div
                                                        key={`${conn.connectionId}-${table.table_name}-${table.schema || ''}`}
                                                        onClick={() => {
                                                            if (assignmentMode === 'manual') {
                                                                toggleTableSelection(table.connection_id, table.table_name)
                                                            } else {
                                                                setSelectedTable({ connectionId: table.connection_id, tableName: table.table_name })
                                                            }
                                                        }}
                                                        className={cn(
                                                            "p-3 rounded-lg border transition-all",
                                                            assignmentMode === 'manual' 
                                                                ? "cursor-pointer"
                                                                : "cursor-pointer",
                                                            isSelected
                                                                ? "bg-blue-100 dark:bg-blue-900/40 border-blue-400 dark:border-blue-600 ring-2 ring-blue-300 dark:ring-blue-700"
                                                                : "bg-white dark:bg-gray-900 border-gray-200 dark:border-gray-800 hover:border-blue-300 dark:hover:border-blue-700 hover:shadow-sm",
                                                            selectedTable?.connectionId === table.connection_id && selectedTable?.tableName === table.table_name && assignmentMode !== 'manual' && "ring-2 ring-blue-500 border-blue-500"
                                                        )}
                                                    >
                                                        <div className="flex items-start justify-between gap-3">
                                                            <div className="flex-1 min-w-0">
                                                                <div className="flex items-center gap-2 mb-2">
                                                                    <div className={cn(
                                                                        "p-1.5 rounded-md flex-shrink-0",
                                                                        isSelected
                                                                            ? "bg-blue-200 dark:bg-blue-800"
                                                                            : "bg-blue-50 dark:bg-blue-900/20"
                                                                    )}>
                                                                        <Table className={cn(
                                                                            "w-3 h-3",
                                                                            isSelected
                                                                                ? "text-blue-700 dark:text-blue-300"
                                                                                : "text-blue-600 dark:text-blue-400"
                                                                        )} />
                                                                    </div>
                                                                    <div className="min-w-0">
                                                                        <span className={cn(
                                                                            "font-semibold text-xs",
                                                                            isSelected
                                                                                ? "text-blue-900 dark:text-blue-100"
                                                                                : "text-foreground"
                                                                        )}>
                                                                            {table.table_name}
                                                                        </span>
                                                                        {table.schema && (
                                                                            <span className={cn(
                                                                                "text-[11px] ml-2",
                                                                                isSelected
                                                                                    ? "text-blue-700 dark:text-blue-300"
                                                                                    : "text-muted-foreground"
                                                                            )}>
                                                                                ({table.schema})
                                                                            </span>
                                                                        )}
                                                                    </div>
                                                                    {isSelected && (
                                                                        <CheckCircle2 className="w-4 h-4 text-blue-600 dark:text-blue-400 flex-shrink-0" />
                                                                    )}
                                                                </div>
                                                                
                                                                {/* Crews with access */}
                                                                <div className="ml-6 space-y-2">
                                                                    {table.row_count !== undefined && table.row_count !== null && (
                                                                        <div className={cn(
                                                                            "text-[11px] flex items-center gap-1 mb-2",
                                                                            isSelected
                                                                                ? "text-blue-700 dark:text-blue-300"
                                                                                : "text-muted-foreground"
                                                                        )}>
                                                                            <FileText className="w-3 h-3" />
                                                                            {table.row_count.toLocaleString()} linhas
                                                                        </div>
                                                                    )}
                                                                    
                                                                    {/* Crews permissions - only show when not in manual assignment mode */}
                                                                    {assignmentMode !== 'manual' && (
                                                                        <div className="space-y-1.5">
                                                                            <div className="text-[11px] font-medium text-muted-foreground mb-1.5">
                                                                                Permissões de Crews:
                                                                            </div>
                                                                            {(() => {
                                                                                const allCrews = spaceCrews[selectedSpace] || []
                                                                                if (allCrews.length === 0) {
                                                                                    return (
                                                                                        <span className="text-[11px] text-muted-foreground italic">
                                                                                            Nenhuma crew disponível neste space
                                                                                        </span>
                                                                                    )
                                                                                }
                                                                                
                                                                                return (
                                                                                    <div className="space-y-1">
                                                                                        {allCrews.map(crew => {
                                                                                            const hasAccess = crewsWithAccess.includes(crew.id)
                                                                                            const isUpdating = false // Could add loading state per crew if needed
                                                                                            
                                                                                            return (
                                                                                                <div
                                                                                                    key={crew.id}
                                                                                                    className={cn(
                                                                                                        "flex items-center gap-2 px-2 py-1.5 rounded-md",
                                                                                                        "hover:bg-gray-50 dark:hover:bg-gray-800/50",
                                                                                                        "transition-colors"
                                                                                                    )}
                                                                                                >
                                                                                                    <input
                                                                                                        type="checkbox"
                                                                                                        checked={hasAccess}
                                                                                                        disabled={isUpdating}
                                                                                                        onChange={async (e) => {
                                                                                                            e.stopPropagation()
                                                                                                            if (e.target.checked) {
                                                                                                                // Grant access
                                                                                                                try {
                                                                                                                    await addCrewToTable(table.connection_id, table.table_name, crew.id)
                                                                                                                } catch (error) {
                                                                                                                    console.error('Error granting access:', error)
                                                                                                                    alert(`Erro ao conceder acesso: ${error instanceof Error ? error.message : 'Erro desconhecido'}`)
                                                                                                                }
                                                                                                            } else {
                                                                                                                // Remove access
                                                                                                                if (confirm(`Remover acesso da crew "${crew.name}" a esta tabela?`)) {
                                                                                                                    try {
                                                                                                                        await removeCrewFromTable(table.connection_id, table.table_name, crew.id)
                                                                                                                    } catch (error) {
                                                                                                                        console.error('Error removing access:', error)
                                                                                                                    }
                                                                                                                }
                                                                                                            }
                                                                                                        }}
                                                                                                        className={cn(
                                                                                                            "w-4 h-4 rounded border-2 cursor-pointer",
                                                                                                            "accent-blue-500",
                                                                                                            "border-gray-300 dark:border-gray-600",
                                                                                                            "disabled:opacity-50 disabled:cursor-not-allowed"
                                                                                                        )}
                                                                                                    />
                                                                                                    <label
                                                                                                        className={cn(
                                                                                                            "text-[11px] font-medium cursor-pointer flex-1",
                                                                                                            hasAccess
                                                                                                                ? "text-foreground"
                                                                                                                : "text-muted-foreground"
                                                                                                        )}
                                                                                                        onClick={(e) => e.stopPropagation()}
                                                                                                    >
                                                                                                        {crew.name}
                                                                                                    </label>
                                                                                                    {hasAccess && (
                                                                                                        <div className={cn(
                                                                                                            "w-1.5 h-1.5 rounded-full",
                                                                                                            "bg-green-500"
                                                                                                        )} title="Acesso concedido" />
                                                                                                    )}
                                                                                                </div>
                                                                                            )
                                                                                        })}
                                                                                    </div>
                                                                                )
                                                                            })()}
                                                                        </div>
                                                                    )}
                                                                </div>
                                                            </div>
                                                            
                                                            {/* Settings button for detailed permissions - only show when not in manual mode */}
                                                            {assignmentMode !== 'manual' && (
                                                                <button
                                                                    onClick={(e) => {
                                                                        e.stopPropagation()
                                                                        setSelectedTable({ connectionId: table.connection_id, tableName: table.table_name })
                                                                    }}
                                                                    className={cn(
                                                                        "p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 flex-shrink-0",
                                                                        "transition-colors"
                                                                    )}
                                                                    title="Gerenciar permissões detalhadas"
                                                                >
                                                                    <Settings className="w-3.5 h-3.5 text-muted-foreground" />
                                                                </button>
                                                            )}
                                                        </div>
                                                    </div>
                                                )
                                            })}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <div className={cn(
                                "p-8 rounded-lg border text-center",
                                "bg-gray-50 dark:bg-gray-900/50",
                                "border-gray-200 dark:border-gray-700"
                            )}>
                                <Table className="w-8 h-8 text-muted-foreground mx-auto mb-2 opacity-50" />
                                <p className="text-sm text-muted-foreground">
                                    Nenhuma tabela encontrada nas conexões deste space.
                                </p>
                                <p className="text-xs text-muted-foreground mt-1">
                                    Certifique-se de que o space tem conexões configuradas e que as tabelas foram descobertas.
                                </p>
                            </div>
                        )}
                        
                        {/* Table Permissions Modal */}
                        {selectedTable && (
                            <TablePermissionsModal
                                isOpen={!!selectedTable}
                                onClose={() => setSelectedTable(null)}
                                connectionId={selectedTable.connectionId}
                                tableName={selectedTable.tableName}
                                spaceId={selectedSpace}
                                spaceCrews={spaceCrews[selectedSpace] || []}
                                crewMembers={crewMembers}
                                permissions={tablePermissions[`${selectedTable.connectionId}:${selectedTable.tableName}`] || []}
                                isDark={isDark}
                            />
                        )}
                    </div>
                </div>
            </div>
        )
    }
    
    // Render add view
    if (viewMode === 'add') {
        const colorOptions = [
            { value: 'blue', label: 'Blue', class: 'bg-blue-500' },
            { value: 'purple', label: 'Purple', class: 'bg-purple-500' },
            { value: 'green', label: 'Green', class: 'bg-green-500' },
            { value: 'orange', label: 'Orange', class: 'bg-orange-500' },
            { value: 'red', label: 'Red', class: 'bg-red-500' },
            { value: 'pink', label: 'Pink', class: 'bg-pink-500' },
        ]
        
        return (
            <div className="h-full flex flex-col">
                {/* Header with Back Button */}
                <div className={cn(
                    "px-5 py-4 border-b",
                    isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
                )}>
                    <div className="flex items-center gap-3 mb-4">
                        <button
                            onClick={handleCancelSpace}
                            className={cn(
                                "p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-white/5 transition-colors"
                            )}
                        >
                            <ChevronLeft className="w-4 h-4" />
                        </button>
                        <div>
                            <h2 className="text-lg font-semibold text-foreground">Create New Space</h2>
                            <p className="text-xs text-muted-foreground">
                                Create a new space for your organization
                            </p>
                        </div>
                    </div>
                </div>
                
                {/* Form Content */}
                <div className="flex-1 overflow-y-auto p-5">
                    <div className="max-w-3xl mx-auto space-y-6">
                        {/* Name */}
                        <div>
                            <label className="text-sm font-medium text-foreground mb-2 block">
                                Name <span className="text-red-500">*</span>
                            </label>
                            <Input
                                value={formData.name}
                                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                placeholder="e.g., Financeiro"
                                className={cn(
                                    "h-10 text-sm",
                                    isDark 
                                        ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                        : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                                )}
                            />
                        </div>
                        
                        {/* Description */}
                        <div>
                            <label className="text-sm font-medium text-foreground mb-2 block">
                                Description
                            </label>
                            <textarea
                                value={formData.description}
                                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                                placeholder="Optional description for this space"
                                rows={3}
                                className={cn(
                                    "w-full rounded-lg text-sm p-3 resize-none",
                                    isDark 
                                        ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                        : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                                )}
                            />
                        </div>
                        
                        {/* Color */}
                        <div>
                            <label className="text-sm font-medium text-foreground mb-2 block">
                                Color
                            </label>
                            <div className="grid grid-cols-6 gap-2">
                                {colorOptions.map(color => (
                                    <button
                                        key={color.value}
                                        onClick={() => setFormData({ ...formData, color: color.value })}
                                        className={cn(
                                            "h-10 rounded-lg border-2 transition-all",
                                            formData.color === color.value
                                                ? "border-blue-500 ring-2 ring-blue-200 dark:ring-blue-800"
                                                : "border-gray-200 dark:border-gray-700 hover:border-gray-300"
                                        )}
                                    >
                                        <div className={cn("w-full h-full rounded", color.class)} />
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
                
                {/* Actions */}
                <div className={cn(
                    "px-5 py-4 border-t",
                    isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
                )}>
                    <div className="max-w-3xl mx-auto flex items-center justify-end gap-3">
                        <button
                            onClick={handleCancelSpace}
                            className={cn(
                                "px-4 py-2 rounded-lg text-sm font-medium",
                                "hover:bg-gray-100 dark:hover:bg-gray-700",
                                "transition-colors"
                            )}
                        >
                            Cancel
                        </button>
                        <button
                            onClick={handleSaveSpace}
                            disabled={!formData.name}
                            className={cn(
                                "px-4 py-2 rounded-lg text-sm font-medium",
                                "bg-primary hover:bg-primary/90 text-primary-foreground",
                                "disabled:opacity-50 disabled:cursor-not-allowed",
                                "transition-colors"
                            )}
                        >
                            Create Space
                        </button>
                    </div>
                </div>
            </div>
        )
    }
    
    return (
        <div className="h-full flex flex-col">
            {/* Header Section */}
            <div className={cn(
                "px-5 py-4 border-b",
                isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
            )}>
                <div className="flex items-start justify-between mb-4">
                    <p className="text-xs text-muted-foreground flex-1">
                        Organize your teams into Spaces. Spaces contain multiple Crews and manage access to connections.
                    </p>
                    <button 
                        onClick={() => {
                            setViewMode('add')
                            setFormData({ name: '', description: '', color: 'blue' })
                        }}
                        className={cn(
                            "px-4 py-2 rounded-lg text-sm font-medium flex items-center gap-2 transition-colors",
                            "bg-primary hover:bg-primary/90 text-primary-foreground"
                        )}
                    >
                        <Plus className="w-4 h-4" />
                        Create New Space
                    </button>
                </div>
                
                {/* Stats Cards */}
                <div className="grid grid-cols-3 gap-4 mb-4">
                    <div className={cn(
                        "p-4 rounded-lg border",
                        "bg-white dark:bg-gray-800",
                        "border-gray-200 dark:border-gray-700"
                    )}>
                        <p className="text-xs text-muted-foreground mb-1">Total spaces</p>
                        <p className="text-2xl font-semibold text-foreground">{stats.total}</p>
                    </div>
                    <div className={cn(
                        "p-4 rounded-lg border",
                        "bg-white dark:bg-gray-800",
                        "border-gray-200 dark:border-gray-700"
                    )}>
                        <p className="text-xs text-muted-foreground mb-1">Total crews</p>
                        <p className="text-2xl font-semibold text-foreground">{stats.totalCrews}</p>
                    </div>
                    <div className={cn(
                        "p-4 rounded-lg border",
                        "bg-white dark:bg-gray-800",
                        "border-gray-200 dark:border-gray-700"
                    )}>
                        <p className="text-xs text-muted-foreground mb-1">Total members</p>
                        <p className="text-2xl font-semibold text-foreground">{stats.totalMembers}</p>
                    </div>
                </div>
                
                {/* Search */}
                <div className="flex items-center gap-3 flex-wrap">
                    <div className="relative flex-1">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/50" />
                        <Input
                            type="text"
                            placeholder="Search spaces..."
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
                </div>
            </div>
            
            {/* Content Area */}
            <div className="flex-1 overflow-y-auto p-5">
                {/* Spaces List - Professional Grid */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                    {paginatedSpaces.map(space => {
                        const spaceStats = getSpaceStats(space.id)
                        
                        // Get color scheme based on space color or generate from name
                        // Unified blue color scheme for all Data Catalog cards
                        const colorScheme = {
                            gradient: 'from-blue-500/10 via-blue-400/5 to-blue-600/10',
                            border: 'border-blue-500/20',
                            icon: 'from-blue-500 to-blue-600',
                            hover: 'hover:border-blue-500/40 hover:from-blue-500/15'
                        }
                        
                        return (
                            <div
                                key={space.id}
                                onClick={(e) => {
                                    if ((e.target as HTMLElement).closest('button')) return
                                    setSelectedSpace(space.id)
                                    setViewMode('detail')
                                }}
                                className={cn(
                                    "group relative overflow-hidden",
                                    "rounded-xl border transition-all duration-300",
                                    "bg-white/80 dark:bg-gray-800/80 backdrop-blur-sm",
                                    colorScheme.border,
                                    "hover:shadow-lg hover:shadow-blue-500/10 dark:hover:shadow-blue-500/20",
                                    "hover:scale-[1.02] hover:-translate-y-0.5",
                                    colorScheme.hover,
                                    "cursor-pointer"
                                )}
                            >
                                {/* Gradient Background */}
                                <div className={cn(
                                    "absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300",
                                    `bg-gradient-to-br ${colorScheme.gradient}`
                                )} />
                                
                                {/* Content */}
                                <div className="relative p-4">
                                    <div className="flex items-start gap-3 mb-3">
                                        {/* Avatar with Gradient */}
                                        <div className={cn(
                                            "flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center",
                                            "bg-gradient-to-br shadow-lg",
                                            colorScheme.icon,
                                            "text-white font-bold text-sm",
                                            "ring-2 ring-white/20 dark:ring-gray-700/50"
                                        )}>
                                            {space.name.charAt(0).toUpperCase()}
                                        </div>
                                        
                                        {/* Space Info */}
                                        <div className="flex-1 min-w-0">
                                            <h3 className="font-semibold text-sm text-foreground truncate group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
                                                {space.name}
                                            </h3>
                                        </div>
                                    </div>
                                    
                                    {/* Stats Badges - Single Line */}
                                    <TooltipProvider delayDuration={0}>
                                        <div className="flex items-center gap-1.5 flex-wrap">
                                            {/* Crews Badge */}
                                            <Tooltip>
                                                <TooltipTrigger asChild>
                                                    <div className={cn(
                                                        "flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] cursor-help",
                                                        "bg-gray-100/80 dark:bg-gray-700/50",
                                                        "backdrop-blur-sm border border-gray-200/50 dark:border-gray-600/50"
                                                    )}>
                                                        <Users className="w-2.5 h-2.5 text-muted-foreground" />
                                                        <span className="font-medium text-foreground">
                                                            {spaceStats.crews}
                                                        </span>
                                                    </div>
                                                </TooltipTrigger>
                                                <TooltipContent side="top" className="text-xs">
                                                    {spaceStats.crews === 1 ? '1 Crew' : `${spaceStats.crews} Crews`}
                                                </TooltipContent>
                                            </Tooltip>
                                            
                                            {/* Members Badge */}
                                            <Tooltip>
                                                <TooltipTrigger asChild>
                                                    <div className={cn(
                                                        "flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] cursor-help",
                                                        "bg-gray-100/80 dark:bg-gray-700/50",
                                                        "backdrop-blur-sm border border-gray-200/50 dark:border-gray-600/50"
                                                    )}>
                                                        <User className="w-2.5 h-2.5 text-muted-foreground" />
                                                        <span className="font-medium text-foreground">
                                                            {spaceStats.members}
                                                        </span>
                                                    </div>
                                                </TooltipTrigger>
                                                <TooltipContent side="top" className="text-xs">
                                                    {spaceStats.members === 1 ? '1 Member' : `${spaceStats.members} Members`}
                                                </TooltipContent>
                                            </Tooltip>
                                            
                                            {/* Connections Badge */}
                                            <Tooltip>
                                                <TooltipTrigger asChild>
                                                    <div className={cn(
                                                        "flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] cursor-help",
                                                        "bg-gray-100/80 dark:bg-gray-700/50",
                                                        "backdrop-blur-sm border border-gray-200/50 dark:border-gray-600/50"
                                                    )}>
                                                        <Database className="w-2.5 h-2.5 text-muted-foreground" />
                                                        <span className="font-medium text-foreground">
                                                            {spaceStats.connections}
                                                        </span>
                                                    </div>
                                                </TooltipTrigger>
                                                <TooltipContent side="top" className="text-xs">
                                                    {spaceStats.connections === 1 ? '1 Connection' : `${spaceStats.connections} Connections`}
                                                </TooltipContent>
                                            </Tooltip>
                                        </div>
                                    </TooltipProvider>
                                    
                                    {/* Hover Indicator */}
                                    <div className={cn(
                                        "absolute bottom-0 left-0 right-0 h-0.5",
                                        "bg-gradient-to-r from-blue-500/0 via-blue-500/50 to-blue-500/0",
                                        "opacity-0 group-hover:opacity-100 transition-opacity duration-300"
                                    )} />
                                </div>
                            </div>
                        )
                    })}
                </div>
                
                {/* Pagination */}
                {totalPages > 1 && (
                    <div className="flex items-center justify-between mt-5">
                        <div className="text-xs text-muted-foreground">
                            {((currentPage - 1) * itemsPerPage) + 1} to {Math.min(currentPage * itemsPerPage, filteredSpaces.length)} of {filteredSpaces.length}
                        </div>
                        <div className="flex items-center gap-2">
                            <button
                                onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                                disabled={currentPage === 1}
                                className={cn(
                                    "px-3 py-1.5 rounded text-sm",
                                    "hover:bg-gray-100 dark:hover:bg-gray-700",
                                    "disabled:opacity-50 disabled:cursor-not-allowed",
                                    "transition-colors"
                                )}
                            >
                                <ChevronLeft className="w-4 h-4" />
                            </button>
                            <span className="text-xs text-muted-foreground">Previous</span>
                            <span className="text-xs text-muted-foreground">Next</span>
                            <button
                                onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                                disabled={currentPage === totalPages}
                                className={cn(
                                    "px-3 py-1.5 rounded text-sm",
                                    "hover:bg-gray-100 dark:hover:bg-gray-700",
                                    "disabled:opacity-50 disabled:cursor-not-allowed",
                                    "transition-colors"
                                )}
                            >
                                <ChevronRight className="w-4 h-4" />
                            </button>
                            <div className="relative ml-2">
                                <select
                                    value={itemsPerPage}
                                    onChange={(e) => {
                                        setItemsPerPage(Number(e.target.value))
                                        setCurrentPage(1)
                                    }}
                                    className={cn(
                                        "h-8 px-2 pr-6 rounded text-xs border",
                                        isDark 
                                            ? "bg-white/4 border-white/8 text-foreground" 
                                            : "bg-white border-black/8 text-foreground",
                                        "appearance-none cursor-pointer"
                                    )}
                                >
                                    <option value="10">10</option>
                                    <option value="12">12</option>
                                    <option value="20">20</option>
                                    <option value="40">40</option>
                                </select>
                                <ChevronDown className="absolute right-1 top-1/2 -translate-y-1/2 w-3 h-3 text-muted-foreground pointer-events-none" />
                            </div>
                        </div>
                    </div>
                )}
            </div>
            
            {/* Delete Confirmation Modal */}
            <DeleteConfirmationModal
                isOpen={deleteModalOpen}
                onClose={() => {
                    setDeleteModalOpen(false)
                    setItemToDelete(null)
                }}
                onConfirm={async () => {
                    if (itemToDelete) {
                        try {
                            const { deleteSpace } = useSpaceStore.getState()
                            await deleteSpace(itemToDelete.id)
                            await fetchSpaces()
                        } catch (error) {
                            console.error('Error deleting space:', error)
                        }
                    }
                }}
                itemName={itemToDelete?.name || ''}
                itemType="space"
                isDark={isDark}
            />
        </div>
    )
}

// ============================================
// CREWS SECTION - Separate Section
// ============================================
export function CrewsSection({ isDark }: { isDark: boolean }) {
    // Use real stores
    const { spaces, fetchSpaces } = useSpaceStore()
    const { crews, fetchCrews, crewMembers, fetchCrewMembers } = useCrewStore()
    
    // State for crew members
    const [crewMembersList, setCrewMembersList] = useState<Record<string, ApiCrewMember[]>>({})
    const [isLoadingMembers, setIsLoadingMembers] = useState(false)
    
    // State for table permissions per member
    const [spaceTables, setSpaceTables] = useState<SpaceTable[]>([])
    const [memberTablePermissions, setMemberTablePermissions] = useState<Record<string, TableMemberPermission[]>>({})
    const [expandedMember, setExpandedMember] = useState<string | null>(null)
    const [isLoadingTables, setIsLoadingTables] = useState(false)
    const [savingPermissions, setSavingPermissions] = useState<Record<string, boolean>>({})
    
    const [searchQuery, setSearchQuery] = useState('')
    const [filterSpace, setFilterSpace] = useState<string>('all')
    const [selectedCrew, setSelectedCrew] = useState<string | null>(null)
    const [viewMode, setViewMode] = useState<'list' | 'detail' | 'add'>('list')
    const [deleteModalOpen, setDeleteModalOpen] = useState(false)
    const [itemToDelete, setItemToDelete] = useState<{ id: string; name: string } | null>(null)
    const [currentPage, setCurrentPage] = useState(1)
    const [itemsPerPage, setItemsPerPage] = useState(10)
    const [formData, setFormData] = useState({ name: '', description: '', spaceId: '' })
    
    // Load spaces and crews on mount
    useEffect(() => {
        fetchSpaces().catch(console.error)
        fetchCrews().catch(console.error)
    }, [fetchSpaces, fetchCrews])
    
    // Load members for all crews when crews are loaded
    useEffect(() => {
        crews.forEach(crew => {
            if (!crewMembers[crew.id]) {
                fetchCrewMembers(crew.id).catch(console.error)
            }
        })
    }, [crews, crewMembers, fetchCrewMembers])
    
    // Load members when a crew is selected in detail view
    useEffect(() => {
        if (selectedCrew && viewMode === 'detail') {
            loadCrewMembers(selectedCrew)
        }
    }, [selectedCrew, viewMode])
    
    // Load space tables when crew is selected
    useEffect(() => {
        if (selectedCrew && viewMode === 'detail') {
            const currentCrew = crews.find(c => c.id === selectedCrew)
            if (currentCrew?.space_id) {
                loadSpaceTablesForCrew(currentCrew.space_id)
            }
        }
    }, [selectedCrew, viewMode, crews])
    
    // Reload permissions when member is expanded and tables are loaded
    useEffect(() => {
        if (expandedMember && spaceTables.length > 0 && selectedCrew) {
            console.log(`[CrewsSection] Member ${expandedMember} expanded, reloading permissions`)
            loadMemberTablePermissions(expandedMember)
        }
    }, [expandedMember, spaceTables.length, selectedCrew])
    
    const loadCrewMembers = async (crewId: string) => {
        setIsLoadingMembers(true)
        try {
            const members = await crewsApi.getCrewMembers(crewId)
            setCrewMembersList(prev => ({ ...prev, [crewId]: members }))
            // Also ensure the store is updated
            if (!crewMembers[crewId] || crewMembers[crewId].length !== members.length) {
                await fetchCrewMembers(crewId)
            }
        } catch (error) {
            console.error('Error loading crew members:', error)
        } finally {
            setIsLoadingMembers(false)
        }
    }
    
    const loadSpaceTablesForCrew = async (spaceId: string) => {
        setIsLoadingTables(true)
        try {
            const tables = await spacesApi.getSpaceTables(spaceId)
            setSpaceTables(tables)
        } catch (error) {
            console.error('Error loading space tables:', error)
        } finally {
            setIsLoadingTables(false)
        }
    }
    
    const loadMemberTablePermissions = async (memberId: string) => {
        try {
            console.log(`[CrewsSection] Loading permissions for member ${memberId}`)
            // Load permissions for all tables this member has access to
            const allPermissions: TableMemberPermission[] = []
            
            for (const table of spaceTables) {
                try {
                    const permissions = await permissionsApi.getTableMemberPermissions(
                        table.connection_id,
                        table.table_name
                    )
                    console.log(`[CrewsSection] Permissions for table ${table.table_name}:`, permissions)
                    const memberPerms = permissions.filter(p => p.member_id === memberId && p.crew_id === selectedCrew)
                    allPermissions.push(...memberPerms)
                } catch (error) {
                    console.error(`Error loading permissions for table ${table.table_name}:`, error)
                    // If table has no permissions yet, that's okay - continue
                }
            }
            
            console.log(`[CrewsSection] Total permissions loaded for member ${memberId}:`, allPermissions.length)
            setMemberTablePermissions(prev => ({
                ...prev,
                [memberId]: allPermissions
            }))
        } catch (error) {
            console.error(`Error loading table permissions for member ${memberId}:`, error)
        }
    }
    
    const toggleMemberTableAccess = async (
        memberId: string,
        connectionId: string,
        tableName: string,
        crewId: string,
        hasAccess: boolean
    ) => {
        const permissionKey = `${memberId}:${connectionId}:${tableName}`
        setSavingPermissions(prev => ({ ...prev, [permissionKey]: true }))
        
        try {
            console.log(`[CrewsSection] Toggling access for member ${memberId}, table ${tableName}, hasAccess: ${hasAccess}`)
            const existingPerms = memberTablePermissions[memberId] || []
            const existingPerm = existingPerms.find(
                p => p.connection_id === connectionId && p.table_name === tableName && p.crew_id === crewId
            )
            
            if (hasAccess) {
                if (!existingPerm) {
                    // Create new permission
                    console.log(`[CrewsSection] Creating new permission for member ${memberId}, table ${tableName}`)
                    const newPerm = await permissionsApi.createTableMemberPermission({
                        connection_id: connectionId,
                        table_name: tableName,
                        crew_id: crewId,
                        member_id: memberId,
                        has_access: "true"
                    })
                    console.log(`[CrewsSection] Created permission:`, newPerm)
                } else if (existingPerm.has_access === "false") {
                    // Update existing permission
                    console.log(`[CrewsSection] Updating permission ${existingPerm.id} to grant access`)
                    await permissionsApi.updateTableMemberPermission(existingPerm.id, {
                        has_access: "true"
                    })
                }
            } else {
                if (existingPerm) {
                    if (existingPerm.has_access === "true") {
                        // Update to remove access
                        console.log(`[CrewsSection] Updating permission ${existingPerm.id} to remove access`)
                        await permissionsApi.updateTableMemberPermission(existingPerm.id, {
                            has_access: "false"
                        })
                    }
                }
            }
            
            // Reload permissions to ensure UI is in sync
            console.log(`[CrewsSection] Reloading permissions for member ${memberId}`)
            await loadMemberTablePermissions(memberId)
            
            console.log(`[CrewsSection] Successfully toggled access for member ${memberId}, table ${tableName}`)
        } catch (error) {
            console.error('[CrewsSection] Error toggling table access:', error)
            alert(`Erro ao ${hasAccess ? 'conceder' : 'remover'} acesso: ${error instanceof Error ? error.message : 'Erro desconhecido'}`)
            // Reload permissions even on error to ensure UI is correct
            await loadMemberTablePermissions(memberId)
        } finally {
            setSavingPermissions(prev => {
                const newState = { ...prev }
                delete newState[permissionKey]
                return newState
            })
        }
    }
    
    const getMemberTableAccess = (memberId: string, connectionId: string, tableName: string): boolean => {
        const permissions = memberTablePermissions[memberId] || []
        const perm = permissions.find(
            p => p.connection_id === connectionId && 
                 p.table_name === tableName && 
                 p.crew_id === selectedCrew
        )
        const hasAccess = perm?.has_access === "true"
        console.log(`[CrewsSection] getMemberTableAccess: member=${memberId}, table=${tableName}, hasAccess=${hasAccess}, perm=`, perm)
        return hasAccess
    }
    
    const filteredCrews = crews.filter(crew => {
        const matchesSearch = crew.name.toLowerCase().includes(searchQuery.toLowerCase())
        const matchesSpace = filterSpace === 'all' || crew.space_id === filterSpace
        return matchesSearch && matchesSpace
    })
    
    const paginatedCrews = filteredCrews.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage)
    const totalPages = Math.ceil(filteredCrews.length / itemsPerPage)
    
    // Calculate stats including members from crewMembersList as fallback
    const stats = {
        total: crews.length,
        totalMembers: (() => {
            const allMemberIds = new Set<string>()
            // Use crewMembers from store first
            Object.values(crewMembers).forEach(members => {
                members.forEach(m => allMemberIds.add(m.user_id))
            })
            // Also check crewMembersList as fallback
            Object.values(crewMembersList).forEach(members => {
                members.forEach(m => allMemberIds.add(m.user_id))
            })
            return allMemberIds.size
        })(),
        totalConnections: 0, // TODO: Calculate from permissions
    }
    
    const handleSaveCrew = async () => {
        try {
            if (selectedCrew) {
                // Update existing
                await useCrewStore.getState().updateCrew(selectedCrew, {
                    name: formData.name,
                    description: formData.description || undefined,
                    space_id: formData.spaceId || undefined,
                })
            } else {
                // Create new
                await useCrewStore.getState().createCrew({
                    name: formData.name,
                    description: formData.description || undefined,
                    space_id: formData.spaceId,
                })
            }
            
            // Refresh crews list
            await fetchCrews()
            
            // Reset
            setViewMode('list')
            setSelectedCrew(null)
            setFormData({ name: '', description: '', spaceId: '' })
        } catch (error) {
            console.error('Error saving crew:', error)
            alert('Falha ao salvar a crew. Verifique os dados e tente novamente.')
        }
    }
    
    const handleCancelCrew = () => {
        setViewMode('list')
        setSelectedCrew(null)
        setFormData({ name: '', description: '', spaceId: '' })
    }
    
    // Initialize form data when adding
    useEffect(() => {
        if (viewMode === 'add') {
            setFormData({ name: '', description: '', spaceId: '' })
        }
    }, [viewMode])
    
    // Prefill form when entering detail
    useEffect(() => {
        if (viewMode === 'detail' && selectedCrew) {
            const currentCrew = crews.find(c => c.id === selectedCrew)
            if (currentCrew) {
                setFormData({
                    name: currentCrew.name,
                    description: currentCrew.description || '',
                    spaceId: currentCrew.space_id || ''
                })
            }
        }
    }, [viewMode, selectedCrew, crews])
    
    // Render detail view - show members when crew is selected
    if (viewMode === 'detail' && selectedCrew) {
        const currentCrew = crews.find(c => c.id === selectedCrew)
        if (!currentCrew) {
            setViewMode('list')
            setSelectedCrew(null)
            return null
        }
        
        const space = spaces.find(s => s.id === currentCrew.space_id)
        const members = crewMembersList[selectedCrew] || []
        
        return (
            <div className="h-full flex flex-col">
                {/* Header with Back Button */}
                <div className={cn(
                    "px-5 py-4 border-b",
                    isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
                )}>
                    <div className="flex items-center gap-3">
                        <button
                            onClick={() => {
                                setViewMode('list')
                                setSelectedCrew(null)
                            }}
                            className={cn(
                                "p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-white/5 transition-colors"
                            )}
                        >
                            <ChevronLeft className="w-4 h-4" />
                        </button>
                        <div className="flex items-center gap-3">
                            <div className={cn(
                                "w-10 h-10 rounded-lg flex items-center justify-center text-white font-bold",
                                "bg-purple-500"
                            )}>
                                {currentCrew.name.charAt(0).toUpperCase()}
                            </div>
                            <div>
                                <h2 className="text-lg font-semibold text-foreground">{currentCrew.name}</h2>
                                <p className="text-xs text-muted-foreground">
                                    {space?.name || 'Crew'} • {members.length} {members.length === 1 ? 'membro' : 'membros'}
                                </p>
                            </div>
                        </div>
                    </div>
                </div>
                
                {/* Members Content - Focused View */}
                <div className="flex-1 overflow-y-auto p-5">
                    <div className="max-w-4xl mx-auto">
                        <div className="flex items-center justify-between mb-4">
                            <div>
                                <h3 className="text-sm font-semibold text-foreground">Integrantes da Crew</h3>
                                <p className="text-xs text-muted-foreground mt-1">
                                    Visualize os membros e as tabelas associadas a cada pessoa
                                </p>
                            </div>
                            <button
                                onClick={() => loadCrewMembers(selectedCrew)}
                                disabled={isLoadingMembers}
                                className={cn(
                                    "px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-2",
                                    "bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600",
                                    "disabled:opacity-50 disabled:cursor-not-allowed",
                                    "transition-colors"
                                )}
                            >
                                <RefreshCw className={cn("w-3 h-3", isLoadingMembers && "animate-spin")} />
                                Atualizar
                            </button>
                        </div>
                        {isLoadingMembers ? (
                            <div className="flex items-center gap-2 text-sm text-muted-foreground py-8">
                                <RefreshCw className="w-4 h-4 animate-spin" />
                                Carregando membros...
                            </div>
                        ) : members.length > 0 ? (
                            <div className="space-y-4">
                                {members.map((member) => {
                                    const isExpanded = expandedMember === member.id
                                    // Load permissions when member is first rendered or expanded
                                    const memberTables = spaceTables.filter(table => 
                                        getMemberTableAccess(member.id, table.connection_id, table.table_name)
                                    )
                                    const memberHasAccess = memberTables.length
                                    
                                    return (
                                        <div
                                            key={member.id}
                                            className={cn(
                                                "rounded-lg border transition-all",
                                                "bg-white dark:bg-gray-800",
                                                "border-gray-200 dark:border-gray-700",
                                                isExpanded && "border-blue-300 dark:border-blue-700 shadow-md"
                                            )}
                                        >
                                            {/* Member Header - Clickable to expand/collapse */}
                                            <div
                                                className={cn(
                                                    "p-4 cursor-pointer",
                                                    "hover:bg-gray-50 dark:hover:bg-gray-700/50",
                                                    "transition-colors"
                                                )}
                                                onClick={async () => {
                                                    if (!isExpanded) {
                                                        setExpandedMember(member.id)
                                                        // Load permissions when expanding
                                                        await loadMemberTablePermissions(member.id)
                                                    } else {
                                                        setExpandedMember(null)
                                                    }
                                                }}
                                            >
                                                <div className="flex items-center justify-between">
                                                    <div className="flex items-center gap-3">
                                                        <div className={cn(
                                                            "w-10 h-10 rounded-full flex items-center justify-center text-white font-semibold text-sm",
                                                            "bg-blue-500"
                                                        )}>
                                                            {(member.user?.name || member.user?.email || member.user_id).charAt(0).toUpperCase()}
                                                        </div>
                                                        <div>
                                                            <p className="font-medium text-sm text-foreground">
                                                                {member.user?.name || member.user?.email || `User ${member.user_id.slice(0, 8)}`}
                                                            </p>
                                                            <p className="text-xs text-muted-foreground">
                                                                {member.role || 'Sem função definida'}
                                                                {member.user?.email && ` • ${member.user.email}`}
                                                            </p>
                                                        </div>
                                                    </div>
                                                    <div className="flex items-center gap-2">
                                                        {spaceTables.length > 0 && (
                                                            <span className={cn(
                                                                "text-xs px-2 py-1 rounded-full",
                                                                memberHasAccess > 0
                                                                    ? "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400"
                                                                    : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"
                                                            )}>
                                                                {memberHasAccess} de {spaceTables.length} tabelas
                                                            </span>
                                                        )}
                                                        <ChevronDown className={cn(
                                                            "w-4 h-4 text-muted-foreground transition-transform",
                                                            isExpanded && "transform rotate-180"
                                                        )} />
                                                    </div>
                                                </div>
                                            </div>
                                            
                                            {/* Expanded Table Permissions - Show tables associated with this member */}
                                            {isExpanded && (
                                                <div className="border-t border-gray-200 dark:border-gray-700 p-4">
                                                    <div className="mb-3">
                                                        <h4 className="text-sm font-semibold text-foreground mb-1">
                                                            Tabelas Associadas
                                                        </h4>
                                                        <p className="text-xs text-muted-foreground">
                                                            Visualize e gerencie as tabelas que este membro pode acessar
                                                        </p>
                                                    </div>
                                                    
                                                    {isLoadingTables ? (
                                                        <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
                                                            <RefreshCw className="w-4 h-4 animate-spin" />
                                                            Carregando tabelas...
                                                        </div>
                                                    ) : spaceTables.length === 0 ? (
                                                        <div className="text-sm text-muted-foreground py-4 text-center">
                                                            Nenhuma tabela disponível no space desta crew
                                                        </div>
                                                    ) : (
                                                        <div className="space-y-2 max-h-[400px] overflow-y-auto">
                                                            {Object.values(
                                                                spaceTables.reduce((acc, table) => {
                                                                    const key = table.connection_id
                                                                    if (!acc[key]) {
                                                                        acc[key] = {
                                                                            connectionId: table.connection_id,
                                                                            connectionName: table.connection_name,
                                                                            connectionType: table.connection_type || 'database',
                                                                            tables: [] as SpaceTable[],
                                                                        }
                                                                    }
                                                                    acc[key].tables.push(table)
                                                                    return acc
                                                                }, {} as Record<string, { connectionId: string; connectionName: string; connectionType: string; tables: SpaceTable[] }>)
                                                            ).map((conn) => (
                                                                <div
                                                                    key={conn.connectionId}
                                                                    className={cn(
                                                                        "rounded-lg border p-3",
                                                                        "bg-gray-50 dark:bg-gray-900/50",
                                                                        "border-gray-200 dark:border-gray-700"
                                                                    )}
                                                                >
                                                                    <div className="flex items-center gap-2 mb-2">
                                                                        <Database className="w-4 h-4 text-muted-foreground" />
                                                                        <span className="text-xs font-semibold text-foreground">
                                                                            {conn.connectionName}
                                                                        </span>
                                                                        <span className="text-[10px] uppercase text-muted-foreground">
                                                                            {conn.connectionType}
                                                                        </span>
                                                                    </div>
                                                                    <div className="space-y-1 ml-6">
                                                                        {conn.tables.map((table) => {
                                                                            const hasAccess = getMemberTableAccess(
                                                                                member.id,
                                                                                table.connection_id,
                                                                                table.table_name
                                                                            )
                                                                            const permissionKey = `${member.id}:${table.connection_id}:${table.table_name}`
                                                                            const isSaving = savingPermissions[permissionKey] || false
                                                                            
                                                                            return (
                                                                                <div
                                                                                    key={`${table.connection_id}-${table.table_name}`}
                                                                                    className={cn(
                                                                                        "flex items-center justify-between p-2 rounded border",
                                                                                        "bg-white dark:bg-gray-800",
                                                                                        hasAccess 
                                                                                            ? "border-green-200 dark:border-green-800 bg-green-50/50 dark:bg-green-900/20"
                                                                                            : "border-gray-200 dark:border-gray-700",
                                                                                        isSaving && "opacity-50"
                                                                                    )}
                                                                                >
                                                                                    <div className="flex items-center gap-2">
                                                                                        <Table className={cn(
                                                                                            "w-3 h-3",
                                                                                            hasAccess ? "text-green-600 dark:text-green-400" : "text-muted-foreground"
                                                                                        )} />
                                                                                        <span className={cn(
                                                                                            "text-xs",
                                                                                            hasAccess ? "text-foreground font-medium" : "text-foreground"
                                                                                        )}>
                                                                                            {table.table_name}
                                                                                        </span>
                                                                                        {table.schema && (
                                                                                            <span className="text-[10px] text-muted-foreground">
                                                                                                ({table.schema})
                                                                                            </span>
                                                                                        )}
                                                                                        {isSaving && (
                                                                                            <RefreshCw className="w-3 h-3 text-blue-500 animate-spin" />
                                                                                        )}
                                                                                    </div>
                                                                                    <label className={cn(
                                                                                        "relative inline-flex items-center cursor-pointer",
                                                                                        isSaving && "cursor-wait"
                                                                                    )}>
                                                                                        <input
                                                                                            type="checkbox"
                                                                                            checked={hasAccess}
                                                                                            disabled={isSaving}
                                                                                            onChange={(e) => {
                                                                                                toggleMemberTableAccess(
                                                                                                    member.id,
                                                                                                    table.connection_id,
                                                                                                    table.table_name,
                                                                                                    selectedCrew!,
                                                                                                    e.target.checked
                                                                                                )
                                                                                            }}
                                                                                            className="sr-only peer"
                                                                                        />
                                                                                        <div className={cn(
                                                                                            "w-9 h-5 rounded-full peer transition-colors",
                                                                                            hasAccess
                                                                                                ? "bg-blue-500"
                                                                                                : "bg-gray-300 dark:bg-gray-600",
                                                                                            isSaving && "opacity-50",
                                                                                            "peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-300",
                                                                                            "peer-checked:after:translate-x-full peer-checked:after:border-white",
                                                                                            "after:content-[''] after:absolute after:top-[2px] after:left-[2px]",
                                                                                            "after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all"
                                                                                        )} />
                                                                                    </label>
                                                                                </div>
                                                                            )
                                                                        })}
                                                                    </div>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    )
                                })}
                            </div>
                        ) : (
                            <div className={cn(
                                "p-8 rounded-lg border text-center",
                                "bg-gray-50 dark:bg-gray-900/50",
                                "border-gray-200 dark:border-gray-700"
                            )}>
                                <Users className="w-8 h-8 text-muted-foreground mx-auto mb-2 opacity-50" />
                                <p className="text-sm text-muted-foreground">
                                    Nenhum membro encontrado nesta crew.
                                </p>
                                <p className="text-xs text-muted-foreground mt-1">
                                    Adicione membros através do gerenciamento da crew.
                                </p>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        )
    }
    
    // Render add view
    if (viewMode === 'add') {
        const currentCrew = null
        const isEditing = false
        
        return (
            <div className="h-full flex flex-col">
                {/* Header with Back Button */}
                <div className={cn(
                    "px-5 py-4 border-b",
                    isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
                )}>
                    <div className="flex items-center gap-3 mb-4">
                        <button
                            onClick={handleCancelCrew}
                            className={cn(
                                "p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-white/5 transition-colors"
                            )}
                        >
                            <ChevronLeft className="w-4 h-4" />
                        </button>
                        <div>
                            <h2 className="text-lg font-semibold text-foreground">
                                {isEditing ? 'Edit Crew' : 'Create New Crew'}
                            </h2>
                            <p className="text-xs text-muted-foreground">
                                {isEditing ? 'Update crew information' : 'Create a new crew within a space'}
                            </p>
                        </div>
                    </div>
                </div>
                
                {/* Form Content */}
                <div className="flex-1 overflow-y-auto p-5">
                    <div className="max-w-3xl mx-auto space-y-6">
                        {/* Name */}
                        <div>
                            <label className="text-sm font-medium text-foreground mb-2 block">
                                Name <span className="text-red-500">*</span>
                            </label>
                            <Input
                                value={formData.name}
                                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                placeholder="e.g., Salários"
                                className={cn(
                                    "h-10 text-sm",
                                    isDark 
                                        ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                        : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                                )}
                            />
                        </div>
                        
                        {/* Space */}
                        <div>
                            <label className="text-sm font-medium text-foreground mb-2 block">
                                Space <span className="text-red-500">*</span>
                            </label>
                            <div className="relative">
                                <select
                                    value={formData.spaceId}
                                    onChange={(e) => setFormData({ ...formData, spaceId: e.target.value })}
                                    className={cn(
                                        "h-10 w-full px-3 pr-8 rounded-lg text-sm border appearance-none cursor-pointer",
                                        isDark 
                                            ? "bg-white/4 border-white/8 text-foreground" 
                                            : "bg-white border-black/8 text-foreground"
                                    )}
                                >
                                    <option value="">Select a space</option>
                                    {spaces.map(space => (
                                        <option key={space.id} value={space.id}>{space.name}</option>
                                    ))}
                                </select>
                                <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                            </div>
                        </div>
                        
                        {/* Description */}
                        <div>
                            <label className="text-sm font-medium text-foreground mb-2 block">
                                Description
                            </label>
                            <textarea
                                value={formData.description}
                                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                                placeholder="Optional description for this crew"
                                rows={3}
                                className={cn(
                                    "w-full rounded-lg text-sm p-3 resize-none",
                                    isDark 
                                        ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                        : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                                )}
                            />
                        </div>
                    </div>
                </div>
                
                {/* Actions */}
                <div className={cn(
                    "px-5 py-4 border-t",
                    isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
                )}>
                    <div className="max-w-3xl mx-auto flex items-center justify-end gap-3">
                        <button
                            onClick={handleCancelCrew}
                            className={cn(
                                "px-4 py-2 rounded-lg text-sm font-medium",
                                "hover:bg-gray-100 dark:hover:bg-gray-700",
                                "transition-colors"
                            )}
                        >
                            Cancel
                        </button>
                        <button
                            onClick={() => {
                                if (selectedCrew) {
                                    const currentCrew = crews.find(c => c.id === selectedCrew)
                                    setItemToDelete({ id: selectedCrew, name: currentCrew?.name || '' })
                                    setDeleteModalOpen(true)
                                }
                            }}
                            disabled={!selectedCrew}
                            className={cn(
                                "px-4 py-2 rounded-lg text-sm font-medium",
                                "bg-red-500 hover:bg-red-600 text-white",
                                "disabled:opacity-50 disabled:cursor-not-allowed",
                                "transition-colors"
                            )}
                        >
                            Delete
                        </button>
                        <button
                            onClick={handleSaveCrew}
                            disabled={!formData.name || !formData.spaceId}
                            className={cn(
                                "px-4 py-2 rounded-lg text-sm font-medium",
                                "bg-blue-500 hover:bg-blue-600 text-white",
                                "disabled:opacity-50 disabled:cursor-not-allowed",
                                "transition-colors"
                            )}
                        >
                            {isEditing ? 'Save Changes' : 'Create Crew'}
                        </button>
                    </div>
                </div>
                
                {/* Delete Confirmation Modal */}
                <DeleteConfirmationModal
                    isOpen={deleteModalOpen}
                    onClose={() => {
                        setDeleteModalOpen(false)
                        setItemToDelete(null)
                    }}
                    onConfirm={async () => {
                        if (itemToDelete) {
                            try {
                                await useCrewStore.getState().deleteCrew(itemToDelete.id)
                                await fetchCrews()
                                setViewMode('list')
                                setSelectedCrew(null)
                            } catch (error) {
                                console.error('Error deleting crew:', error)
                            }
                        }
                    }}
                    itemName={itemToDelete?.name || ''}
                    itemType="crew"
                    isDark={isDark}
                />
            </div>
        )
    }
    
    return (
        <div className="h-full flex flex-col">
            {/* Header Section */}
            <div className={cn(
                "px-5 py-4 border-b",
                isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
            )}>
                <div className="flex items-start justify-between mb-4">
                    <p className="text-xs text-muted-foreground flex-1">
                        Manage Crews within Spaces. Crews contain team members with specific roles and access to connections.
                    </p>
                    <button
                        onClick={() => {
                            setViewMode('add')
                            setFormData({ name: '', description: '', spaceId: '' })
                        }}
                        className={cn(
                            "px-4 py-2 rounded-lg text-sm font-medium flex items-center gap-2 transition-colors",
                            "bg-primary hover:bg-primary/90 text-primary-foreground"
                        )}
                    >
                        <Plus className="w-4 h-4" />
                        Create New Crew
                    </button>
                </div>
                
                {/* Stats Cards */}
                <div className="grid grid-cols-3 gap-4 mb-4">
                    <div className={cn(
                        "p-4 rounded-lg border",
                        "bg-white dark:bg-gray-800",
                        "border-gray-200 dark:border-gray-700"
                    )}>
                        <p className="text-xs text-muted-foreground mb-1">Total crews</p>
                        <p className="text-2xl font-semibold text-foreground">{stats.total}</p>
                    </div>
                    <div className={cn(
                        "p-4 rounded-lg border",
                        "bg-white dark:bg-gray-800",
                        "border-gray-200 dark:border-gray-700"
                    )}>
                        <p className="text-xs text-muted-foreground mb-1">Total members</p>
                        <p className="text-2xl font-semibold text-foreground">{stats.totalMembers}</p>
                    </div>
                    <div className={cn(
                        "p-4 rounded-lg border",
                        "bg-white dark:bg-gray-800",
                        "border-gray-200 dark:border-gray-700"
                    )}>
                        <p className="text-xs text-muted-foreground mb-1">Total connections</p>
                        <p className="text-2xl font-semibold text-foreground">{stats.totalConnections}</p>
                    </div>
                </div>
                
                {/* Search and Filters */}
                <div className="flex items-center gap-3 flex-wrap">
                    <div className="relative flex-1">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/50" />
                        <Input
                            type="text"
                            placeholder="Search crews..."
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
                    <div className="relative">
                        <select
                            value={filterSpace}
                            onChange={(e) => setFilterSpace(e.target.value)}
                            className={cn(
                                "h-9 px-3 pr-8 rounded-lg text-xs border",
                                isDark 
                                    ? "bg-white/4 border-white/8 text-foreground" 
                                    : "bg-white border-black/8 text-foreground",
                                "appearance-none cursor-pointer"
                            )}
                        >
                            <option value="all">All Spaces</option>
                            {spaces.map(space => (
                                <option key={space.id} value={space.id}>{space.name}</option>
                            ))}
                        </select>
                        <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                    </div>
                </div>
            </div>
            
            {/* Content Area */}
            <div className="flex-1 overflow-y-auto p-5">
                {/* Crews List - Professional Grid */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                    {paginatedCrews.map(crew => {
                        // Use crewMembers from store first, fallback to crewMembersList
                        const members = crewMembers[crew.id] || crewMembersList[crew.id] || []
                        
                        // Unified blue color scheme for all Data Catalog cards
                        const colorScheme = {
                            gradient: 'from-blue-500/10 via-blue-400/5 to-blue-600/10',
                            border: 'border-blue-500/20',
                            icon: 'from-blue-500 to-blue-600',
                            hover: 'hover:border-blue-500/40 hover:from-blue-500/15'
                        }
                        
                        return (
                            <div
                                key={crew.id}
                                onClick={(e) => {
                                    if ((e.target as HTMLElement).closest('button')) return
                                    setSelectedCrew(crew.id)
                                    setViewMode('detail')
                                }}
                                className={cn(
                                    "group relative overflow-hidden",
                                    "rounded-xl border transition-all duration-300",
                                    "bg-white/80 dark:bg-gray-800/80 backdrop-blur-sm",
                                    colorScheme.border,
                                    "hover:shadow-lg hover:shadow-blue-500/10 dark:hover:shadow-blue-500/20",
                                    "hover:scale-[1.02] hover:-translate-y-0.5",
                                    colorScheme.hover,
                                    "cursor-pointer"
                                )}
                            >
                                {/* Gradient Background */}
                                <div className={cn(
                                    "absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300",
                                    `bg-gradient-to-br ${colorScheme.gradient}`
                                )} />
                                
                                {/* Content */}
                                <div className="relative p-4">
                                    <div className="flex items-start gap-3">
                                        {/* Avatar with Gradient */}
                                        <div className={cn(
                                            "flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center",
                                            "bg-gradient-to-br shadow-lg",
                                            colorScheme.icon,
                                            "text-white font-bold text-sm",
                                            "ring-2 ring-white/20 dark:ring-gray-700/50"
                                        )}>
                                            {crew.name.charAt(0).toUpperCase()}
                                        </div>
                                        
                                        {/* Crew Info */}
                                        <div className="flex-1 min-w-0 flex flex-col gap-2">
                                            <div>
                                                <h3 className="font-semibold text-sm text-foreground truncate group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
                                                    {crew.name}
                                                </h3>
                                            </div>
                                            
                                            {/* Member Count Badge */}
                                            <TooltipProvider delayDuration={0}>
                                                <Tooltip>
                                                    <TooltipTrigger asChild>
                                                        <div className={cn(
                                                            "flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] cursor-help",
                                                            "bg-gray-100/80 dark:bg-gray-700/50",
                                                            "backdrop-blur-sm border border-gray-200/50 dark:border-gray-600/50"
                                                        )}>
                                                            <Users className="w-2.5 h-2.5 text-muted-foreground" />
                                                            <span className="font-medium text-foreground">
                                                                {members.length}
                                                            </span>
                                                        </div>
                                                    </TooltipTrigger>
                                                    <TooltipContent side="top" className="text-xs">
                                                        {members.length === 1 ? '1 Member' : `${members.length} Members`}
                                                    </TooltipContent>
                                                </Tooltip>
                                            </TooltipProvider>
                                        </div>
                                    </div>
                                    
                                    {/* Hover Indicator */}
                                    <div className={cn(
                                        "absolute bottom-0 left-0 right-0 h-0.5",
                                        "bg-gradient-to-r from-blue-500/0 via-blue-500/50 to-blue-500/0",
                                        "opacity-0 group-hover:opacity-100 transition-opacity duration-300"
                                    )} />
                                </div>
                            </div>
                        )
                    })}
                </div>
                
                {/* Pagination */}
                {totalPages > 1 && (
                    <div className="flex items-center justify-between mt-5">
                        <div className="text-xs text-muted-foreground">
                            {((currentPage - 1) * itemsPerPage) + 1} to {Math.min(currentPage * itemsPerPage, filteredCrews.length)} of {filteredCrews.length}
                        </div>
                        <div className="flex items-center gap-2">
                            <button
                                onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                                disabled={currentPage === 1}
                                className={cn(
                                    "px-3 py-1.5 rounded text-sm",
                                    "hover:bg-gray-100 dark:hover:bg-gray-700",
                                    "disabled:opacity-50 disabled:cursor-not-allowed",
                                    "transition-colors"
                                )}
                            >
                                <ChevronLeft className="w-4 h-4" />
                            </button>
                            <span className="text-xs text-muted-foreground">Previous</span>
                            <span className="text-xs text-muted-foreground">Next</span>
                            <button
                                onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                                disabled={currentPage === totalPages}
                                className={cn(
                                    "px-3 py-1.5 rounded text-sm",
                                    "hover:bg-gray-100 dark:hover:bg-gray-700",
                                    "disabled:opacity-50 disabled:cursor-not-allowed",
                                    "transition-colors"
                                )}
                            >
                                <ChevronRight className="w-4 h-4" />
                            </button>
                            <div className="relative ml-2">
                                <select
                                    value={itemsPerPage}
                                    onChange={(e) => {
                                        setItemsPerPage(Number(e.target.value))
                                        setCurrentPage(1)
                                    }}
                                    className={cn(
                                        "h-8 px-2 pr-6 rounded text-xs border",
                                        isDark 
                                            ? "bg-white/4 border-white/8 text-foreground" 
                                            : "bg-white border-black/8 text-foreground",
                                        "appearance-none cursor-pointer"
                                    )}
                                >
                                    <option value="10">10</option>
                                    <option value="12">12</option>
                                    <option value="20">20</option>
                                    <option value="40">40</option>
                                </select>
                                <ChevronDown className="absolute right-1 top-1/2 -translate-y-1/2 w-3 h-3 text-muted-foreground pointer-events-none" />
                            </div>
                        </div>
                    </div>
                )}
            </div>
            
            {/* Delete Confirmation Modal */}
            <DeleteConfirmationModal
                isOpen={deleteModalOpen}
                onClose={() => {
                    setDeleteModalOpen(false)
                    setItemToDelete(null)
                }}
                onConfirm={async () => {
                    if (itemToDelete) {
                        try {
                            await useCrewStore.getState().deleteCrew(itemToDelete.id)
                            await fetchCrews()
                        } catch (error) {
                            console.error('Error deleting crew:', error)
                        }
                    }
                }}
                itemName={itemToDelete?.name || ''}
                itemType="crew"
                isDark={isDark}
            />
        </div>
    )
}

