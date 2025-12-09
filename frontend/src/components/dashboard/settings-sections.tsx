"use client"

import React, { useState, useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { 
    X, Search, Database, Shield, Users, Plus, Eye, Trash2, Edit2, 
    ChevronLeft, ChevronRight, MoreVertical, RefreshCw, ArrowUpDown, 
    CheckCircle2, ChevronDown, UserPlus, Clock, Info, Settings,
    Crown, Navigation, Compass, User, MoreHorizontal, Server, Key, Link2,
    FileText, Globe, AlertCircle
} from "lucide-react"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { 
    CONNECTOR_REGISTRY, 
    getConnectorById, 
    getConnectorsByCategory,
    ConnectorDefinition 
} from "@/lib/connectors/connector-registry"
import { DataConnection, ConnectionMetadata, Space, Crew, CrewMember, ConnectionPermission } from "@/lib/types/connections"
import { DynamicFormField } from "./dynamic-form-field"

// ============================================
// ACTIONS DROPDOWN COMPONENT
// ============================================
interface ActionsDropdownProps {
    isOpen: boolean
    onClose: () => void
    onEdit: () => void
    onDelete: () => void
    onPermissions?: () => void
    buttonRef: React.RefObject<HTMLButtonElement>
    isDark: boolean
}

function ActionsDropdown({ isOpen, onClose, onEdit, onDelete, onPermissions, buttonRef, isDark }: ActionsDropdownProps) {
    const [position, setPosition] = useState({ top: 0, left: 0 })
    
    useEffect(() => {
        if (isOpen && buttonRef.current) {
            const rect = buttonRef.current.getBoundingClientRect()
            setPosition({
                top: rect.bottom + 4,
                left: rect.right - 120 // Align dropdown to right edge of button
            })
        }
    }, [isOpen, buttonRef])
    
    useEffect(() => {
        if (!isOpen) return
        
        const handleClickOutside = (e: MouseEvent) => {
            if (buttonRef.current && !buttonRef.current.contains(e.target as Node)) {
                onClose()
            }
        }
        
        document.addEventListener('mousedown', handleClickOutside)
        return () => document.removeEventListener('mousedown', handleClickOutside)
    }, [isOpen, onClose, buttonRef])
    
    if (!isOpen) return null
    
    return (
        <>
            <div 
                className="fixed inset-0 z-10" 
                onClick={onClose}
            />
            <div
                className={cn(
                    "absolute z-20 min-w-[120px] rounded-lg border shadow-lg",
                    "bg-white dark:bg-gray-800",
                    "border-gray-200 dark:border-gray-700",
                    "py-1"
                )}
                style={{ top: position.top, left: position.left }}
            >
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
// DELETE CONFIRMATION MODAL COMPONENT
// ============================================
interface DeleteConfirmationModalProps {
    isOpen: boolean
    onClose: () => void
    onConfirm: () => void
    itemName: string
    itemType: 'connection' | 'space' | 'crew' | 'user'
    isDark: boolean
}

function DeleteConfirmationModal({ isOpen, onClose, onConfirm, itemName, itemType, isDark }: DeleteConfirmationModalProps) {
    const [confirmName, setConfirmName] = useState('')
    const isValid = confirmName === itemName
    
    useEffect(() => {
        if (!isOpen) {
            setConfirmName('')
        }
    }, [isOpen])
    
    if (!isOpen) return null
    
    const itemTypeLabel = {
        connection: 'connection',
        space: 'space',
        crew: 'crew',
        user: 'user'
    }[itemType]
    
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
                        className={cn(
                            "h-10 text-sm",
                            isDark 
                                ? "bg-white/4 border-white/8 focus:border-white/15 focus:bg-white/6" 
                                : "bg-white border-black/8 focus:border-black/15 focus:bg-white"
                        )}
                        autoFocus
                    />
                </div>
                <div className="flex items-center justify-end gap-3">
                    <button
                        onClick={onClose}
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
                            if (isValid) {
                                onConfirm()
                                onClose()
                            }
                        }}
                        disabled={!isValid}
                        className={cn(
                            "px-4 py-2 rounded-lg text-sm font-medium",
                            "bg-red-500 hover:bg-red-600 text-white",
                            "disabled:opacity-50 disabled:cursor-not-allowed",
                            "transition-colors"
                        )}
                    >
                        Delete
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
    const [viewMode, setViewMode] = useState<'list' | 'detail' | 'permissions' | 'add'>('list')
    const [selectedConnectionForPermissions, setSelectedConnectionForPermissions] = useState<string | null>(null)
    const [permissionsTab, setPermissionsTab] = useState<'spaces' | 'crew'>('spaces')
    const [addConnectionStep, setAddConnectionStep] = useState<1 | 2 | 3>(1)
    const [selectedConnectionType, setSelectedConnectionType] = useState<'database' | 'document' | 'api' | null>(null)
    const [selectedConnectorForAdd, setSelectedConnectorForAdd] = useState<ConnectorDefinition | null>(null)
    
    // Connections state
    const [connections, setConnections] = useState<DataConnection[]>([
        { 
            id: '1', 
            name: 'Classic Models', 
            connectorId: 'mysql',
            status: 'active', 
            lastSync: '2025-01-15T10:30:00Z',
            nextSync: '2025-01-15T16:30:00Z',
            syncFrequency: '0 */6 * * *',
            config: { host: 'mysql.example.com', port: 3306, database: 'classic_models', username: 'admin' },
            description: 'Database related with car models and manufacturing.',
            createdAt: '2025-01-10T08:00:00Z',
            updatedAt: '2025-01-15T10:30:00Z',
            metadata: {
                tables: [
                    { name: 'customers', schema: 'public', rowCount: 122, columns: [] },
                    { name: 'orders', schema: 'public', rowCount: 326, columns: [] }
                ],
                schemas: [{ name: 'public', tables: ['customers', 'orders'] }],
                lastMetadataUpdate: '2025-01-15T10:30:00Z'
            }
        },
        { 
            id: '2', 
            name: 'Adventure Works', 
            connectorId: 'postgres',
            status: 'inactive', 
            lastSync: '2025-01-10T14:20:00Z',
            nextSync: '2025-01-10T20:20:00Z',
            syncFrequency: '0 */6 * * *',
            config: { host: 'postgres.example.com', port: 5432, database: 'adventureworks', username: 'postgres' },
            description: 'Sample database used for testing purposes.',
            createdAt: '2025-01-08T09:00:00Z',
            updatedAt: '2025-01-10T14:20:00Z'
        },
        { 
            id: '3', 
            name: 'Sales Spreadsheet', 
            connectorId: 'google-sheets',
            status: 'active', 
            lastSync: '2025-01-15T09:15:00Z',
            nextSync: '2025-01-15T15:15:00Z',
            syncFrequency: '0 */6 * * *',
            config: { spreadsheet_link: 'https://docs.google.com/spreadsheets/d/1hLd9Qqti3UyLXZB2aFfUWDT7B6arw2xy4HR3D-dwUb/edit' },
            description: 'Sales data from Google Sheets.',
            createdAt: '2025-01-12T11:00:00Z',
            updatedAt: '2025-01-15T09:15:00Z'
        },
    ])
    
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
    const [deleteModalOpen, setDeleteModalOpen] = useState(false)
    const [itemToDelete, setItemToDelete] = useState<{ id: string; name: string } | null>(null)
    const [currentPage, setCurrentPage] = useState(1)
    const [itemsPerPage, setItemsPerPage] = useState(4)
    
    
    // Permissions state
    const [spaces] = useState<Space[]>([
        { id: '1', name: 'Financeiro', crewIds: ['1', '2'], connectionIds: ['1'], createdAt: '' },
        { id: '2', name: 'Marketing', crewIds: ['3'], connectionIds: ['2'], createdAt: '' }
    ])
    
    const [crews] = useState<Crew[]>([
        { id: '1', name: 'Salários', spaceId: '1', memberIds: [], connectionIds: ['1'], createdAt: '' },
        { id: '2', name: 'Pagamento', spaceId: '1', memberIds: [], connectionIds: ['1'], createdAt: '' },
        { id: '3', name: 'Campanhas', spaceId: '2', memberIds: [], connectionIds: ['2'], createdAt: '' }
    ])
    
    const [permissions, setPermissions] = useState<ConnectionPermission[]>([
        { connectionId: '1', spaceId: '1', accessLevel: 'full' },
        { connectionId: '1', crewId: '1', tableAccess: ['customers', 'orders'], accessLevel: 'custom' },
        { connectionId: '1', crewId: '2', tableAccess: ['products'], accessLevel: 'custom' },
        { connectionId: '2', spaceId: '2', accessLevel: 'full' },
    ])
    
    // Form state for add/edit
    const [formData, setFormData] = useState<Record<string, any>>({
        name: '',
        description: '',
    })
    
    // Get connection permissions
    const getConnectionPermissions = (connectionId: string) => {
        return permissions.filter(p => p.connectionId === connectionId)
    }
    
    const getSpacePermissions = (spaceId: string) => {
        return permissions.filter(p => p.spaceId === spaceId)
    }
    
    const getCrewPermissions = (crewId: string) => {
        return permissions.filter(p => p.crewId === crewId)
    }
    
    const addPermission = (permission: ConnectionPermission) => {
        setPermissions([...permissions, permission])
    }
    
    const removePermission = (connectionId: string, spaceId?: string, crewId?: string) => {
        setPermissions(permissions.filter(p => 
            !(p.connectionId === connectionId && 
              (spaceId ? p.spaceId === spaceId : !p.spaceId) &&
              (crewId ? p.crewId === crewId : !p.crewId))
        ))
    }
    
    const updateTableAccess = (connectionId: string, crewId: string, tables: string[]) => {
        setPermissions(permissions.map(p => 
            p.connectionId === connectionId && p.crewId === crewId
                ? { ...p, tableAccess: tables, accessLevel: 'custom' }
                : p
        ))
    }

    const filteredConnections = connections.filter(conn => {
        const connector = getConnectorById(conn.connectorId)
        const matchesSearch = conn.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
                            conn.description?.toLowerCase().includes(searchQuery.toLowerCase())
        const matchesCategory = filterCategory === 'all' || connector?.category === filterCategory
        const matchesStatus = filterStatus === 'all' || conn.status === filterStatus
        
        // Filter by space
        const connPermissions = getConnectionPermissions(conn.id)
        const connSpaces = connPermissions.filter(p => p.spaceId).map(p => p.spaceId!)
        const matchesSpace = filterSpace === 'all' || connSpaces.includes(filterSpace)
        
        // Filter by crew
        const connCrews = connPermissions.filter(p => p.crewId).map(p => p.crewId!)
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

    // No pagination for now - show all filtered connections
    const uniqueCategories = Array.from(new Set(connections.map(c => {
        const connector = getConnectorById(c.connectorId)
        return connector?.category || 'unknown'
    })))

    const deleteConnection = (id: string) => {
        setConnections(connections.filter(c => c.id !== id))
        if (selectedConnection === id) setSelectedConnection(null)
    }


    
    const handleEditConnection = (connId: string) => {
        const conn = connections.find(c => c.id === connId)
        if (!conn) return
        const connector = getConnectorById(conn.connectorId)
        if (!connector) return
        
        setEditingConnection(connId)
        setSelectedConnector(connector)
        setSelectedAuthMethod(connector.authMethods[0]?.type || '')
        setViewMode('detail')
        setFormData({
            name: conn.name,
            description: conn.description || '',
            ...conn.config
        })
    }
    
    const handleTestConnection = async () => {
        const connector = selectedConnector || selectedConnectorForAdd
        if (!connector) return
        setTestingConnection(editingConnection || 'new')
        setTestResult(null)
        
        // Simulate connection test
        setTimeout(() => {
            const success = Math.random() > 0.3 // 70% success rate for demo
            setTestResult({
                success,
                message: success 
                    ? 'Connection successful! All credentials are valid.'
                    : 'Connection failed. Please check your credentials and try again.'
            })
            setTestingConnection(null)
        }, 2000)
    }
    
    const handleSaveConnection = () => {
        const connector = selectedConnector || selectedConnectorForAdd
        if (!connector) return
        
        if (editingConnection) {
            // Update existing
            setConnections(connections.map(c => 
                c.id === editingConnection
                    ? {
                        ...c,
                        name: formData.name,
                        description: formData.description || '',
                        config: { ...formData },
                        updatedAt: new Date().toISOString()
                    }
                    : c
            ))
        } else {
            // Create new
            const newConnection: DataConnection = {
                id: Date.now().toString(),
                name: formData.name,
                connectorId: connector.id,
                status: 'active',
                lastSync: undefined,
                nextSync: undefined,
                syncFrequency: connector.syncFrequency.default,
                config: { ...formData },
                description: formData.description || '',
                createdAt: new Date().toISOString(),
                updatedAt: new Date().toISOString(),
            }
            setConnections([...connections, newConnection])
        }
        
        // Reset
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
    
    const handleCancelEdit = () => {
        setViewMode('list')
        setEditingConnection(null)
        setSelectedConnector(null)
        setSelectedAuthMethod('')
        setFormData({ name: '', description: '' })
        setTestResult(null)
    }

    const handleSyncNow = (connectionId: string) => {
        // Simulate sync
        setConnections(connections.map(c => 
            c.id === connectionId 
                ? { ...c, lastSync: new Date().toISOString(), status: 'active' }
                : c
        ))
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
        const spacePerms = connPermissions.filter(p => p.spaceId)
        const crewPerms = connPermissions.filter(p => p.crewId)
        
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
                                            // TODO: Open modal to add space permission
                                        }}
                                        className={cn(
                                            "px-4 py-2 rounded-lg text-sm font-medium",
                                            "bg-blue-500 hover:bg-blue-600 text-white",
                                            "transition-colors"
                                        )}
                                    >
                                        Add Space Access
                                    </button>
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    {spacePerms.map(perm => {
                                        const space = spaces.find(s => s.id === perm.spaceId)
                                        if (!space) return null
                                        const spaceCrews = crews.filter(c => c.spaceId === space.id)
                                        const totalMembers = spaceCrews.reduce((sum, crew) => sum + crew.memberIds.length, 0)
                                        
                                        return (
                                            <div
                                                key={perm.spaceId}
                                                className={cn(
                                                    "p-4 rounded-lg border",
                                                    "bg-white dark:bg-gray-800",
                                                    "border-gray-200 dark:border-gray-700"
                                                )}
                                            >
                                                <div className="flex items-center justify-between mb-3">
                                                    <div>
                                                        <h3 className="text-sm font-semibold text-foreground">{space.name}</h3>
                                                        <p className="text-xs text-muted-foreground mt-1">Access Level: {perm.accessLevel}</p>
                                                    </div>
                                                    <button
                                                        onClick={() => removePermission(conn.id, perm.spaceId)}
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
                                                        <p className="text-sm font-semibold text-foreground">{spaceCrews.length}</p>
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
                                            // TODO: Open modal to add crew permission
                                        }}
                                        className={cn(
                                            "px-4 py-2 rounded-lg text-sm font-medium",
                                            "bg-blue-500 hover:bg-blue-600 text-white",
                                            "transition-colors"
                                        )}
                                    >
                                        Add Crew Access
                                    </button>
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    {crewPerms.map(perm => {
                                        const crew = crews.find(c => c.id === perm.crewId)
                                        if (!crew) return null
                                        const space = spaces.find(s => s.id === crew.spaceId)
                                        
                                        return (
                                            <div
                                                key={perm.crewId}
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
                                                            {space?.name} • Access Level: {perm.accessLevel}
                                                        </p>
                                                    </div>
                                                    <button
                                                        onClick={() => removePermission(conn.id, undefined, perm.crewId)}
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
                                                        <p className="text-sm font-semibold text-foreground">{crew.memberIds.length}</p>
                                                    </div>
                                                    <div>
                                                        <p className="text-xs text-muted-foreground mb-1">Tables Access</p>
                                                        <p className="text-sm font-semibold text-foreground">
                                                            {perm.tableAccess?.length || 0} / {conn.metadata?.tables?.length || 0}
                                                        </p>
                                                    </div>
                                                    <div>
                                                        <p className="text-xs text-muted-foreground mb-1">Last Updated</p>
                                                        <p className="text-sm font-semibold text-foreground">
                                                            {conn.updatedAt ? new Date(conn.updatedAt).toLocaleDateString() : 'N/A'}
                                                        </p>
                                                    </div>
                                                </div>
                                                {perm.tableAccess && perm.tableAccess.length > 0 && (
                                                    <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-700">
                                                        <p className="text-xs text-muted-foreground mb-2">Accessible Tables:</p>
                                                        <div className="flex flex-wrap gap-1.5">
                                                            {perm.tableAccess.map(tableName => (
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
            </div>
        )
    }
    
    // Render add connection view with 3 steps
    if (viewMode === 'add') {
        const availableConnectors = selectedConnectionType 
            ? getConnectorsByCategory(selectedConnectionType)
            : []
        
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
                                setAddConnectionStep(1)
                                setSelectedConnectionType(null)
                                setSelectedConnectorForAdd(null)
                                setFormData({ name: '', description: '' })
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
                                Step {addConnectionStep} of 3
                            </p>
                        </div>
                    </div>
                    
                    {/* Progress Indicator */}
                    <div className="flex items-center justify-center gap-2 mb-4">
                        {[1, 2, 3].map((step) => (
                            <div key={step} className="flex items-center">
                                <div className={cn(
                                    "w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium",
                                    addConnectionStep >= step
                                        ? "bg-blue-500 text-white"
                                        : "bg-gray-200 dark:bg-gray-700 text-muted-foreground"
                                )}>
                                    {step}
                                </div>
                                {step < 3 && (
                                    <div className={cn(
                                        "w-12 h-0.5 mx-2",
                                        addConnectionStep > step ? "bg-blue-500" : "bg-gray-200 dark:bg-gray-700"
                                    )} />
                                )}
                            </div>
                        ))}
                    </div>
                </div>
                
                {/* Step Content */}
                <div className="flex-1 overflow-y-auto p-5">
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
                                                    onClick={() => {
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
                                                            onChange={(e) => setSelectedAuthMethod(e.target.value)}
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
                    </div>
                </div>
                
                {/* Actions */}
                <div className={cn(
                    "px-5 py-4 border-t",
                    isDark ? "border-white/5 bg-gray-900/20" : "border-black/5 bg-gray-50/50"
                )}>
                    <div className="max-w-3xl mx-auto flex items-center justify-end gap-3">
                        {addConnectionStep > 1 && (
                            <button
                                onClick={() => {
                                    if (addConnectionStep === 2) {
                                        setAddConnectionStep(1)
                                        setSelectedConnectorForAdd(null)
                                    } else if (addConnectionStep === 3) {
                                        setAddConnectionStep(2)
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
                        {addConnectionStep < 3 ? (
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
                                    "bg-blue-500 hover:bg-blue-600 text-white",
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
                                    disabled={testingConnection !== null}
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
                                    onClick={handleSaveConnection}
                                    className={cn(
                                        "px-4 py-2 rounded-lg text-sm font-medium",
                                        "bg-blue-500 hover:bg-blue-600 text-white",
                                        "transition-colors"
                                    )}
                                >
                                    Create Connection
                                </button>
                            </>
                        )}
                    </div>
                </div>
            </div>
        )
    }
    
    // Render connection detail view
    if (viewMode === 'detail' && selectedConnector) {
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
                                {editingConnection ? 'Edit Connection' : 'New Connection'}
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
                            onClick={handleSaveConnection}
                            disabled={!isFormValid()}
                            className={cn(
                                "px-4 py-2 rounded-lg text-sm font-medium",
                                "bg-blue-500 hover:bg-blue-600 text-white",
                                "disabled:opacity-50 disabled:cursor-not-allowed",
                                "transition-colors"
                            )}
                        >
                            {editingConnection ? 'Save Changes' : 'Create Connection'}
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
                            "bg-blue-500 hover:bg-blue-600 text-white",
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
                {/* Connections List - Rectangular Cards */}
                <div className="space-y-3">
                        {paginatedConnections.map((conn) => {
                            const connector = getConnectorById(conn.connectorId)
                            if (!connector) return null
                            const Icon = connector.icon
                            
                            // Get connection stats
                            const connPermissions = getConnectionPermissions(conn.id)
                            const connSpaces = connPermissions.filter(p => p.spaceId).map(p => spaces.find(s => s.id === p.spaceId)).filter(Boolean)
                            const connCrews = connPermissions.filter(p => p.crewId).map(p => crews.find(c => c.id === p.crewId)).filter(Boolean)
                            const tableCount = conn.metadata?.tables?.length || 0
                            const totalTables = 100 // Mock total - in real app this would come from metadata
                            const usagePercentage = totalTables > 0 ? Math.round((tableCount / totalTables) * 100) : 0
                            
                            return (
                                <div
                                    key={conn.id}
                                    onClick={(e) => {
                                        // Don't navigate if clicking on action buttons
                                        if ((e.target as HTMLElement).closest('button')) return
                                        handleEditConnection(conn.id)
                                    }}
                                    className={cn(
                                        "relative p-4 rounded-lg border cursor-pointer",
                                        "bg-white dark:bg-gray-800",
                                        "border-gray-200 dark:border-gray-700",
                                        "hover:shadow-md hover:border-blue-300 dark:hover:border-blue-700",
                                        "transition-all duration-200"
                                    )}
                                >
                                    <div className="flex items-center gap-4">
                                        {/* Icon */}
                                        <div className={cn(
                                            "w-12 h-12 rounded-lg flex items-center justify-center flex-shrink-0",
                                            connector.category === 'database' && "bg-blue-100 dark:bg-blue-900/30",
                                            connector.category === 'document' && "bg-green-100 dark:bg-green-900/30",
                                            connector.category === 'api' && "bg-purple-100 dark:bg-purple-900/30"
                                        )}>
                                            <Icon className={cn(
                                                "w-6 h-6",
                                                connector.category === 'database' && "text-blue-600 dark:text-blue-400",
                                                connector.category === 'document' && "text-green-600 dark:text-green-400",
                                                connector.category === 'api' && "text-purple-600 dark:text-purple-400"
                                            )} />
                                        </div>
                                        
                                        {/* Info */}
                                        <div className="flex-1 min-w-0 flex items-center gap-6">
                                            <div className="flex-1">
                                                <div className="flex items-center gap-3 mb-1">
                                                    <h3 className="font-semibold text-sm text-foreground">{conn.name}</h3>
                                                    <span className="text-xs text-muted-foreground">{connector.name}</span>
                                                    <span className={cn(
                                                        "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium",
                                                        conn.status === 'active'
                                                            ? "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400"
                                                            : conn.status === 'error'
                                                            ? "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400"
                                                            : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"
                                                    )}>
                                                        {conn.status === 'active' && <CheckCircle2 className="w-3 h-3" />}
                                                        {conn.status === 'error' && <AlertCircle className="w-3 h-3" />}
                                                        {conn.status === 'active' ? 'Active' : conn.status === 'error' ? 'Error' : 'Inactive'}
                                                    </span>
                                                </div>
                                                <p className="text-xs text-muted-foreground">{conn.description}</p>
                                            </div>
                                            
                                            {/* Stats Row */}
                                            <div className="flex items-center gap-4">
                                                <div className="text-center">
                                                    <p className="text-xs font-semibold text-foreground">{tableCount}</p>
                                                    <p className="text-[10px] text-muted-foreground">Tables</p>
                                                </div>
                                                <div className="text-center">
                                                    <p className="text-xs font-semibold text-foreground">{connSpaces.length}</p>
                                                    <p className="text-[10px] text-muted-foreground">Spaces</p>
                                                </div>
                                                <div className="text-center">
                                                    <p className="text-xs font-semibold text-foreground">{connCrews.length}</p>
                                                    <p className="text-[10px] text-muted-foreground">Crews</p>
                                                </div>
                                                <div className="text-center">
                                                    <p className="text-xs font-semibold text-foreground">{usagePercentage}%</p>
                                                    <p className="text-[10px] text-muted-foreground">Usage</p>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            )
                        })}
                </div>
                
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
                                    <option value="4">4</option>
                                    <option value="8">8</option>
                                    <option value="12">12</option>
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
                onConfirm={() => {
                    if (itemToDelete) {
                        deleteConnection(itemToDelete.id)
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
    
    // Mock data
    const [crews] = useState<Crew[]>([
        { id: '1', name: 'Salários', spaceId: '1', memberIds: [], connectionIds: [], createdAt: '' },
        { id: '2', name: 'Pagamento', spaceId: '1', memberIds: [], connectionIds: [], createdAt: '' },
        { id: '3', name: 'Campanhas', spaceId: '2', memberIds: [], connectionIds: [], createdAt: '' }
    ])
    
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
    const [spaces, setSpaces] = useState<Space[]>([
        {
            id: '1',
            name: 'Financeiro',
            description: 'Space for financial operations and data',
            color: 'blue',
            crewIds: ['1', '2'],
            connectionIds: ['1', '3'],
            createdAt: '2025-01-10T08:00:00Z'
        },
        {
            id: '2',
            name: 'Marketing',
            description: 'Marketing campaigns and analytics',
            color: 'purple',
            crewIds: ['3'],
            connectionIds: ['2'],
            createdAt: '2025-01-12T10:00:00Z'
        }
    ])
    const [crews, setCrews] = useState<Crew[]>([
        {
            id: '1',
            name: 'Salários',
            description: 'Crew handling salary data',
            spaceId: '1',
            memberIds: ['1', '2'],
            connectionIds: ['1'],
            createdAt: '2025-01-10T09:00:00Z'
        },
        {
            id: '2',
            name: 'Pagamento',
            description: 'Crew handling payment data',
            spaceId: '1',
            memberIds: ['2', '3'],
            connectionIds: ['1'],
            createdAt: '2025-01-10T09:30:00Z'
        },
        {
            id: '3',
            name: 'Campanhas',
            description: 'Marketing campaigns crew',
            spaceId: '2',
            memberIds: ['1'],
            connectionIds: ['2'],
            createdAt: '2025-01-12T11:00:00Z'
        }
    ])
    const [crewMembers, setCrewMembers] = useState<CrewMember[]>([
        { userId: '1', crewId: '1', role: 'commander' },
        { userId: '2', crewId: '1', role: 'navigator' },
        { userId: '2', crewId: '2', role: 'commander' },
        { userId: '3', crewId: '2', role: 'explorer' },
        { userId: '1', crewId: '3', role: 'commander' },
    ])
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
        const matchesSpace = selectedSpace ? crew.spaceId === selectedSpace : true
        return matchesSearch && matchesSpace
    })

    const handleAddSpace = () => {
        const newSpace: Space = {
            id: Date.now().toString(),
            name: spaceFormData.name,
            description: spaceFormData.description,
            color: spaceFormData.color,
            crewIds: [],
            connectionIds: [],
            createdAt: new Date().toISOString()
        }
        setSpaces([...spaces, newSpace])
        setShowAddSpaceModal(false)
        setSpaceFormData({ name: '', description: '', color: 'blue' })
    }

    const handleAddCrew = () => {
        const newCrew: Crew = {
            id: Date.now().toString(),
            name: crewFormData.name,
            description: crewFormData.description,
            spaceId: crewFormData.spaceId,
            memberIds: [],
            connectionIds: [],
            createdAt: new Date().toISOString()
        }
        setCrews([...crews, newCrew])
        // Update space to include this crew
        setSpaces(spaces.map(s => 
            s.id === crewFormData.spaceId 
                ? { ...s, crewIds: [...s.crewIds, newCrew.id] }
                : s
        ))
        setShowAddCrewModal(false)
        setCrewFormData({ name: '', description: '', spaceId: '' })
    }

    const deleteSpace = (id: string) => {
        // Remove crews in this space
        const spaceCrews = crews.filter(c => c.spaceId === id)
        setCrews(crews.filter(c => c.spaceId !== id))
        // Remove crew members
        setCrewMembers(crewMembers.filter(cm => !spaceCrews.some(sc => sc.id === cm.crewId)))
        setSpaces(spaces.filter(s => s.id !== id))
    }

    const deleteCrew = (id: string) => {
        const crew = crews.find(c => c.id === id)
        if (crew) {
            // Remove from space
            setSpaces(spaces.map(s => 
                s.id === crew.spaceId 
                    ? { ...s, crewIds: s.crewIds.filter(cid => cid !== id) }
                    : s
            ))
        }
        setCrews(crews.filter(c => c.id !== id))
        setCrewMembers(crewMembers.filter(cm => cm.crewId !== id))
    }

    const getCrewMembers = (crewId: string) => {
        return crewMembers
            .filter(cm => cm.crewId === crewId)
            .map(cm => {
                const user = users.find(u => u.id === cm.userId)
                return { ...cm, user }
            })
    }

    const getSpaceStats = (spaceId: string) => {
        const spaceCrews = crews.filter(c => c.spaceId === spaceId)
        const spaceMembers = new Set(
            spaceCrews.flatMap(c => crewMembers.filter(cm => cm.crewId === c.id).map(cm => cm.userId))
        )
        return {
            crews: spaceCrews.length,
            members: spaceMembers.size,
            connections: spaces.find(s => s.id === spaceId)?.connectionIds.length || 0
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
                                "border-gray-300 dark:border-gray-600",
                                "bg-gray-50/50 dark:bg-gray-900/30",
                                "hover:border-blue-400 hover:bg-blue-50/50 dark:hover:bg-blue-900/20",
                                "hover:shadow-md transition-all duration-200",
                                "flex items-center justify-center gap-2"
                            )}
                        >
                            <Plus className="w-5 h-5 text-muted-foreground" />
                            <span className="text-sm font-medium text-foreground">Create New Space</span>
                        </button>

                        {/* Spaces List */}
                        <div className="grid grid-cols-2 gap-4">
                            {filteredSpaces.map(space => {
                                const stats = getSpaceStats(space.id)
                                const spaceCrews = crews.filter(c => c.spaceId === space.id)
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
                                                    space.color === 'blue' && "bg-blue-500",
                                                    space.color === 'purple' && "bg-purple-500",
                                                    space.color === 'green' && "bg-green-500",
                                                    space.color === 'orange' && "bg-orange-500",
                                                    space.color === 'red' && "bg-red-500",
                                                    space.color === 'pink' && "bg-pink-500",
                                                    !space.color && "bg-gray-500"
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
                                "border-gray-300 dark:border-gray-600",
                                "bg-gray-50/50 dark:bg-gray-900/30",
                                "hover:border-blue-400 hover:bg-blue-50/50 dark:hover:bg-blue-900/20",
                                "hover:shadow-md transition-all duration-200",
                                "flex items-center justify-center gap-2"
                            )}
                        >
                            <Plus className="w-5 h-5 text-muted-foreground" />
                            <span className="text-sm font-medium text-foreground">Create New Crew</span>
                        </button>

                        {/* Crews List */}
                        <div className="grid grid-cols-2 gap-4">
                            {filteredCrews.map(crew => {
                                const space = spaces.find(s => s.id === crew.spaceId)
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
                                                            space.color === 'blue' && "bg-blue-500",
                                                            space.color === 'purple' && "bg-purple-500",
                                                            space.color === 'green' && "bg-green-500",
                                                            space.color === 'orange' && "bg-orange-500",
                                                            space.color === 'red' && "bg-red-500",
                                                            space.color === 'pink' && "bg-pink-500"
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
                                        "bg-blue-500 hover:bg-blue-600 text-white",
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
                                        "bg-blue-500 hover:bg-blue-600 text-white",
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
    
    // Mock data - in real app, this would come from props or context
    const [connections] = useState<DataConnection[]>([
        { 
            id: '1', name: 'Classic Models', connectorId: 'mysql', status: 'active',
            syncFrequency: '0 */6 * * *', config: {}, createdAt: '', updatedAt: '',
            metadata: {
                tables: [
                    { name: 'customers', schema: 'public', columns: [] },
                    { name: 'orders', schema: 'public', columns: [] },
                    { name: 'products', schema: 'public', columns: [] }
                ]
            }
        },
        { 
            id: '2', name: 'Sales Spreadsheet', connectorId: 'google-sheets', status: 'active',
            syncFrequency: '0 */6 * * *', config: {}, createdAt: '', updatedAt: ''
        }
    ])
    
    const [spaces] = useState<Space[]>([
        { id: '1', name: 'Financeiro', crewIds: ['1', '2'], connectionIds: ['1'], createdAt: '' },
        { id: '2', name: 'Marketing', crewIds: ['3'], connectionIds: ['2'], createdAt: '' }
    ])
    
    const [crews] = useState<Crew[]>([
        { id: '1', name: 'Salários', spaceId: '1', memberIds: [], connectionIds: ['1'], createdAt: '' },
        { id: '2', name: 'Pagamento', spaceId: '1', memberIds: [], connectionIds: ['1'], createdAt: '' },
        { id: '3', name: 'Campanhas', spaceId: '2', memberIds: [], connectionIds: ['2'], createdAt: '' }
    ])
    
    const [permissions, setPermissions] = useState<ConnectionPermission[]>([
        { connectionId: '1', spaceId: '1', accessLevel: 'full' },
        { connectionId: '1', crewId: '1', tableAccess: ['customers', 'orders'], accessLevel: 'custom' },
        { connectionId: '1', crewId: '2', tableAccess: ['products'], accessLevel: 'custom' },
        { connectionId: '2', spaceId: '2', accessLevel: 'full' },
    ])

    const getConnectionPermissions = (connectionId: string) => {
        return permissions.filter(p => p.connectionId === connectionId)
    }

    const getSpacePermissions = (spaceId: string) => {
        return permissions.filter(p => p.spaceId === spaceId)
    }

    const getCrewPermissions = (crewId: string) => {
        return permissions.filter(p => p.crewId === crewId)
    }

    const addPermission = (permission: ConnectionPermission) => {
        setPermissions([...permissions, permission])
    }

    const removePermission = (connectionId: string, spaceId?: string, crewId?: string) => {
        setPermissions(permissions.filter(p => 
            !(p.connectionId === connectionId && 
              (spaceId ? p.spaceId === spaceId : !p.spaceId) &&
              (crewId ? p.crewId === crewId : !p.crewId))
        ))
    }

    const updateTableAccess = (connectionId: string, crewId: string, tables: string[]) => {
        setPermissions(permissions.map(p => 
            p.connectionId === connectionId && p.crewId === crewId
                ? { ...p, tableAccess: tables, accessLevel: 'custom' }
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
                                const spacePerms = connPermissions.filter(p => p.spaceId)
                                const crewPerms = connPermissions.filter(p => p.crewId)
                                
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
                                                            const space = spaces.find(s => s.id === perm.spaceId)
                                                            return space ? (
                                                                <div key={perm.spaceId} className="flex items-center justify-between p-2 rounded bg-gray-50 dark:bg-gray-900/30">
                                                                    <span className="text-xs text-foreground">{space.name}</span>
                                                                    <div className="flex items-center gap-2">
                                                                        <span className="text-[10px] text-muted-foreground">{perm.accessLevel}</span>
                                                                        <button
                                                                            onClick={(e) => {
                                                                                e.stopPropagation()
                                                                                removePermission(conn.id, perm.spaceId)
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
                                                                const crew = crews.find(c => c.id === perm.crewId)
                                                                return crew ? (
                                                                    <div key={perm.crewId} className="p-2 rounded bg-gray-50 dark:bg-gray-900/30">
                                                                        <div className="flex items-center justify-between mb-2">
                                                                            <span className="text-xs font-medium text-foreground">{crew.name}</span>
                                                                            <button
                                                                                onClick={(e) => {
                                                                                    e.stopPropagation()
                                                                                    removePermission(conn.id, undefined, perm.crewId)
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
                                                                                            perm.tableAccess?.includes(table.name)
                                                                                                ? "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                                                                                                : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"
                                                                                        )}
                                                                                    >
                                                                                        <input
                                                                                            type="checkbox"
                                                                                            checked={perm.tableAccess?.includes(table.name) || false}
                                                                                            onChange={(e) => {
                                                                                                const currentTables = perm.tableAccess || []
                                                                                                const newTables = e.target.checked
                                                                                                    ? [...currentTables, table.name]
                                                                                                    : currentTables.filter(t => t !== table.name)
                                                                                                updateTableAccess(conn.id, perm.crewId!, newTables)
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
                                    const spaceCrews = crews.filter(c => c.spaceId === space.id)
                                    
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
                                                                const conn = connections.find(c => c.id === perm.connectionId)
                                                                return conn ? (
                                                                    <div key={perm.connectionId} className="flex items-center justify-between p-2 rounded bg-gray-50 dark:bg-gray-900/30">
                                                                        <span className="text-xs text-foreground">{conn.name}</span>
                                                                        <span className="text-[10px] text-muted-foreground">{perm.accessLevel}</span>
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
                                                                                    const conn = connections.find(c => c.id === perm.connectionId)
                                                                                    return conn ? (
                                                                                        <div key={perm.connectionId} className="text-xs">
                                                                                            <span className="text-foreground">{conn.name}</span>
                                                                                            {perm.tableAccess && perm.tableAccess.length > 0 && (
                                                                                                <span className="text-muted-foreground ml-2">
                                                                                                    ({perm.tableAccess.length} tables)
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
    
    // Mock data for spaces and crews
    const [spaces] = useState<Space[]>([
        { id: '1', name: 'Financeiro', crewIds: ['1', '2'], connectionIds: [], createdAt: '' },
        { id: '2', name: 'Marketing', crewIds: ['3'], connectionIds: [], createdAt: '' }
    ])
    
    const [crews] = useState<Crew[]>([
        { id: '1', name: 'Salários', spaceId: '1', memberIds: ['1', '2'], connectionIds: [], createdAt: '' },
        { id: '2', name: 'Pagamento', spaceId: '1', memberIds: ['2', '3'], connectionIds: [], createdAt: '' },
        { id: '3', name: 'Campanhas', spaceId: '2', memberIds: ['1'], connectionIds: [], createdAt: '' }
    ])
    
    const [crewMembers] = useState<CrewMember[]>([
        { userId: '1', crewId: '1', role: 'commander' },
        { userId: '2', crewId: '1', role: 'navigator' },
        { userId: '2', crewId: '2', role: 'commander' },
        { userId: '3', crewId: '2', role: 'explorer' },
        { userId: '1', crewId: '3', role: 'commander' },
    ])
    
    const [users, setUsers] = useState([
        { 
            id: '1', name: 'Felipe Meneses', email: 'felipe.meneses@thedatafirst.com', 
            role: 'Member', status: 'active', lastActive: 'Nov 24 2025', avatar: 'F'
        },
        { 
            id: '2', name: 'Kaique Mendonça', email: 'kaique.mendonca855@gmail.com', 
            role: 'Team Admin', status: 'active', lastActive: 'Nov 28 2025', avatar: 'K'
        },
        { 
            id: '3', name: 'Lucas Ventura Team Blue', email: 'lucasventura.teamblue@gmail.com', 
            role: 'Member', status: 'active', lastActive: 'Nov 21 2025', avatar: 'L'
        },
    ])
    const [searchQuery, setSearchQuery] = useState('')
    const [filterRole, setFilterRole] = useState('all')
    const [filterStatus, setFilterStatus] = useState('all')
    const [filterSpace, setFilterSpace] = useState('all')
    const [filterCrew, setFilterCrew] = useState('all')
    const [selectedUser, setSelectedUser] = useState<string | null>(null)
    const [viewMode, setViewMode] = useState<'list' | 'detail' | 'add'>('list')
    const [currentPage, setCurrentPage] = useState(1)
    const itemsPerPage = 20
    const [deleteModalOpen, setDeleteModalOpen] = useState(false)
    const [itemToDelete, setItemToDelete] = useState<{ id: string; name: string } | null>(null)
    const [formData, setFormData] = useState({ name: '', email: '', role: 'Member', status: 'active' })
    
    // Get user's crews and spaces
    const getUserCrews = (userId: string) => {
        return crewMembers
            .filter(cm => cm.userId === userId)
            .map(cm => {
                const crew = crews.find(c => c.id === cm.crewId)
                const space = crew ? spaces.find(s => s.id === crew.spaceId) : null
                return { ...cm, crew, space }
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
        const matchesCrew = filterCrew === 'all' || userCrews.some(uc => uc.crew?.id === filterCrew)
        
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

    const getAvatarColor = (initial: string) => {
        const colors = ['bg-green-500', 'bg-teal-500', 'bg-red-500', 'bg-blue-500', 'bg-purple-500']
        return colors[initial.charCodeAt(0) % colors.length]
    }
    
    const handleSaveUser = () => {
        if (selectedUser) {
            // Update existing
            setUsers(users.map(u => 
                u.id === selectedUser
                    ? {
                        ...u,
                        name: formData.name,
                        email: formData.email,
                        role: formData.role,
                        status: formData.status
                    }
                    : u
            ))
        } else {
            // Create new
            const newUser = {
                id: Date.now().toString(),
                name: formData.name,
                email: formData.email,
                role: formData.role,
                status: formData.status,
                lastActive: new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }),
                avatar: formData.name.charAt(0).toUpperCase(),
                planets: 0, spaces: 0, crews: 0
            }
            setUsers([...users, newUser])
        }
        
        // Reset
        setViewMode('list')
        setSelectedUser(null)
        setFormData({ name: '', email: '', role: 'Member', status: 'active' })
    }
    
    const handleCancelUser = () => {
        setViewMode('list')
        setSelectedUser(null)
        setFormData({ name: '', email: '', role: 'Member', status: 'active' })
    }
    
    // Initialize form data when editing
    useEffect(() => {
        if (viewMode === 'detail' && selectedUser) {
            const currentUser = users.find(u => u.id === selectedUser)
            if (currentUser) {
                setFormData({
                    name: currentUser.name,
                    email: currentUser.email,
                    role: currentUser.role,
                    status: currentUser.status
                })
            }
        } else if (viewMode === 'add') {
            setFormData({ name: '', email: '', role: 'Member', status: 'active' })
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
                        
                        {/* Role */}
                        <div>
                            <label className="text-sm font-medium text-foreground mb-2 block">
                                Role <span className="text-red-500">*</span>
                            </label>
                            <div className="relative">
                                <select
                                    value={formData.role}
                                    onChange={(e) => setFormData({ ...formData, role: e.target.value })}
                                    className={cn(
                                        "h-10 w-full px-3 pr-8 rounded-lg text-sm border appearance-none cursor-pointer",
                                        isDark 
                                            ? "bg-white/4 border-white/8 text-foreground" 
                                            : "bg-white border-black/8 text-foreground"
                                    )}
                                >
                                    <option value="Member">Member</option>
                                    <option value="Team Admin">Team Admin</option>
                                    <option value="Admin">Admin</option>
                                </select>
                                <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                            </div>
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
                                "bg-blue-500 hover:bg-blue-600 text-white",
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
                    onConfirm={() => {
                        if (itemToDelete) {
                            setUsers(users.filter(u => u.id !== itemToDelete.id))
                            setViewMode('list')
                            setSelectedUser(null)
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
                            setFormData({ name: '', email: '', role: 'Member', status: 'active' })
                        }}
                        className={cn(
                            "px-4 py-2 rounded-lg text-sm font-medium",
                            "bg-blue-500 hover:bg-blue-600 text-white",
                            "flex items-center gap-2 transition-colors"
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
                {/* Users Cards */}
                <div className="space-y-3">
                    {paginatedUsers.map((user) => {
                        const userCrews = getUserCrews(user.id)
                        const userSpaces = getUserSpaces(user.id)
                        return (
                            <div
                                key={user.id}
                                onClick={(e) => {
                                    if ((e.target as HTMLElement).closest('button')) return
                                    setSelectedUser(user.id)
                                    setViewMode('detail')
                                }}
                                className={cn(
                                    "relative p-4 rounded-lg border cursor-pointer",
                                    "bg-white dark:bg-gray-800",
                                    "border-gray-200 dark:border-gray-700",
                                    "hover:shadow-md hover:border-blue-300 dark:hover:border-blue-700",
                                    "transition-all duration-200"
                                )}
                            >
                                <div className="flex items-center gap-4">
                                    {/* Avatar */}
                                    <div className={cn(
                                        "w-12 h-12 rounded-full flex items-center justify-center text-white font-semibold text-lg flex-shrink-0",
                                        getAvatarColor(user.avatar)
                                    )}>
                                        {user.avatar}
                                    </div>
                                    
                                    {/* Info - Horizontal Layout */}
                                    <div className="flex-1 min-w-0 flex items-center gap-6">
                                        <div className="flex-1">
                                            <div className="flex items-center gap-3 mb-1">
                                                <h3 className="font-semibold text-sm text-foreground">{user.name}</h3>
                                                <span className={cn(
                                                    "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium",
                                                    user.status === 'active'
                                                        ? "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400"
                                                        : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"
                                                )}>
                                                    {user.status === 'active' && <CheckCircle2 className="w-3 h-3" />}
                                                    {user.status === 'active' ? 'Active' : 'Inactive'}
                                                </span>
                                            </div>
                                            <p className="text-xs text-muted-foreground">{user.email}</p>
                                        </div>
                                        
                                        {/* Stats - Horizontal */}
                                        <div className="flex items-center gap-6">
                                            <div className="text-center">
                                                <p className="text-xs font-semibold text-foreground">{(user as any).planets || 0}</p>
                                                <p className="text-[10px] text-muted-foreground">Planets</p>
                                            </div>
                                            <div className="text-center">
                                                <p className="text-xs font-semibold text-foreground">{userSpaces.length}</p>
                                                <p className="text-[10px] text-muted-foreground">Spaces</p>
                                            </div>
                                            <div className="text-center">
                                                <p className="text-xs font-semibold text-foreground">{userCrews.length}</p>
                                                <p className="text-[10px] text-muted-foreground">Crews</p>
                                            </div>
                                        </div>
                                    </div>
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
                    onConfirm={() => {
                        if (itemToDelete) {
                            setUsers(users.filter(u => u.id !== itemToDelete.id))
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
                                className={cn(
                                    "h-8 px-2 pr-6 rounded text-xs border",
                                    isDark 
                                        ? "bg-white/4 border-white/8 text-foreground" 
                                        : "bg-white border-black/8 text-foreground",
                                    "appearance-none cursor-pointer"
                                )}
                            >
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
// SPACES SECTION - Separate Section
// ============================================
export function SpacesSection({ isDark }: { isDark: boolean }) {
    const [spaces, setSpaces] = useState<Space[]>([
        {
            id: '1',
            name: 'Financeiro',
            description: 'Space for financial operations and data',
            color: 'blue',
            crewIds: ['1', '2'],
            connectionIds: ['1', '3'],
            createdAt: '2025-01-10T08:00:00Z'
        },
        {
            id: '2',
            name: 'Marketing',
            description: 'Marketing campaigns and analytics',
            color: 'purple',
            crewIds: ['3'],
            connectionIds: ['2'],
            createdAt: '2025-01-12T10:00:00Z'
        }
    ])
    const [crews] = useState<Crew[]>([
        { id: '1', name: 'Salários', spaceId: '1', memberIds: ['1', '2'], connectionIds: [], createdAt: '' },
        { id: '2', name: 'Pagamento', spaceId: '1', memberIds: ['2', '3'], connectionIds: [], createdAt: '' },
        { id: '3', name: 'Campanhas', spaceId: '2', memberIds: ['1'], connectionIds: [], createdAt: '' }
    ])
    const [searchQuery, setSearchQuery] = useState('')
    const [selectedSpace, setSelectedSpace] = useState<string | null>(null)
    const [viewMode, setViewMode] = useState<'list' | 'detail' | 'add'>('list')
    const [deleteModalOpen, setDeleteModalOpen] = useState(false)
    const [itemToDelete, setItemToDelete] = useState<{ id: string; name: string } | null>(null)
    const [currentPage, setCurrentPage] = useState(1)
    const [itemsPerPage, setItemsPerPage] = useState(4)
    const [formData, setFormData] = useState({ name: '', description: '', color: 'blue' })
    
    const filteredSpaces = spaces.filter(space => 
        space.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        space.description?.toLowerCase().includes(searchQuery.toLowerCase())
    )
    
    const paginatedSpaces = filteredSpaces.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage)
    const totalPages = Math.ceil(filteredSpaces.length / itemsPerPage)
    
    const getSpaceStats = (spaceId: string) => {
        const spaceCrews = crews.filter(c => c.spaceId === spaceId)
        const spaceMembers = new Set(
            spaceCrews.flatMap(c => c.memberIds)
        )
        return {
            crews: spaceCrews.length,
            members: spaceMembers.size,
            connections: spaces.find(s => s.id === spaceId)?.connectionIds.length || 0
        }
    }
    
    const stats = {
        total: spaces.length,
        totalCrews: crews.length,
        totalMembers: new Set(crews.flatMap(c => c.memberIds)).size,
    }
    
    const handleSaveSpace = () => {
        if (selectedSpace) {
            // Update existing
            setSpaces(spaces.map(s => 
                s.id === selectedSpace
                    ? {
                        ...s,
                        name: formData.name,
                        description: formData.description || '',
                        color: formData.color,
                        updatedAt: new Date().toISOString()
                    }
                    : s
            ))
        } else {
            // Create new
            const newSpace: Space = {
                id: Date.now().toString(),
                name: formData.name,
                description: formData.description || '',
                color: formData.color,
                crewIds: [],
                connectionIds: [],
                createdAt: new Date().toISOString()
            }
            setSpaces([...spaces, newSpace])
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
    
    // Initialize form data when editing
    useEffect(() => {
        if (viewMode === 'detail' && selectedSpace) {
            const currentSpace = spaces.find(s => s.id === selectedSpace)
            if (currentSpace) {
                setFormData({
                    name: currentSpace.name,
                    description: currentSpace.description || '',
                    color: currentSpace.color || 'blue'
                })
            }
        } else if (viewMode === 'add') {
            setFormData({ name: '', description: '', color: 'blue' })
        }
    }, [viewMode, selectedSpace, spaces])
    
    // Render add/edit view
    if (viewMode === 'add' || (viewMode === 'detail' && selectedSpace)) {
        const currentSpace = selectedSpace ? spaces.find(s => s.id === selectedSpace) : null
        const isEditing = !!currentSpace
        
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
                            <h2 className="text-lg font-semibold text-foreground">
                                {isEditing ? 'Edit Space' : 'Create New Space'}
                            </h2>
                            <p className="text-xs text-muted-foreground">
                                {isEditing ? 'Update space information' : 'Create a new space for your organization'}
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
                            onClick={() => {
                                setItemToDelete({ id: selectedSpace!, name: formData.name })
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
                            onClick={handleSaveSpace}
                            disabled={!formData.name}
                            className={cn(
                                "px-4 py-2 rounded-lg text-sm font-medium",
                                "bg-blue-500 hover:bg-blue-600 text-white",
                                "disabled:opacity-50 disabled:cursor-not-allowed",
                                "transition-colors"
                            )}
                        >
                            {isEditing ? 'Save Changes' : 'Create Space'}
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
                            "px-4 py-2 rounded-lg text-sm font-medium",
                            "bg-blue-500 hover:bg-blue-600 text-white",
                            "flex items-center gap-2 transition-colors"
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
                {/* Spaces List - Rectangular Cards */}
                <div className="space-y-3">
                    {paginatedSpaces.map(space => {
                        const spaceStats = getSpaceStats(space.id)
                        return (
                            <div
                                key={space.id}
                                onClick={(e) => {
                                    if ((e.target as HTMLElement).closest('button')) return
                                    setSelectedSpace(space.id)
                                    setViewMode('detail')
                                }}
                                className={cn(
                                    "relative p-4 rounded-lg border cursor-pointer",
                                    "bg-white dark:bg-gray-800",
                                    "border-gray-200 dark:border-gray-700",
                                    "hover:shadow-md hover:border-blue-300 dark:hover:border-blue-700",
                                    "transition-all duration-200"
                                )}
                            >
                                <div className="flex items-center gap-4">
                                    {/* Icon */}
                                    <div className={cn(
                                        "w-12 h-12 rounded-lg flex items-center justify-center flex-shrink-0 text-white font-bold text-lg",
                                        space.color === 'blue' && "bg-blue-500",
                                        space.color === 'purple' && "bg-purple-500",
                                        space.color === 'green' && "bg-green-500",
                                        space.color === 'orange' && "bg-orange-500",
                                        space.color === 'red' && "bg-red-500",
                                        space.color === 'pink' && "bg-pink-500",
                                        !space.color && "bg-gray-500"
                                    )}>
                                        {space.name.charAt(0).toUpperCase()}
                                    </div>
                                    
                                    {/* Info */}
                                    <div className="flex-1 min-w-0 flex items-center gap-6">
                                        <div className="flex-1">
                                            <div className="flex items-center gap-3 mb-1">
                                                <h3 className="font-semibold text-sm text-foreground">{space.name}</h3>
                                                <span className="text-xs text-muted-foreground">Space</span>
                                            </div>
                                            <p className="text-xs text-muted-foreground">{space.description}</p>
                                        </div>
                                        
                                        {/* Stats Row */}
                                        <div className="flex items-center gap-4">
                                            <div className="text-center">
                                                <p className="text-xs font-semibold text-foreground">{spaceStats.crews}</p>
                                                <p className="text-[10px] text-muted-foreground">Crews</p>
                                            </div>
                                            <div className="text-center">
                                                <p className="text-xs font-semibold text-foreground">{spaceStats.members}</p>
                                                <p className="text-[10px] text-muted-foreground">Members</p>
                                            </div>
                                            <div className="text-center">
                                                <p className="text-xs font-semibold text-foreground">{spaceStats.connections}</p>
                                                <p className="text-[10px] text-muted-foreground">Connections</p>
                                            </div>
                                        </div>
                                    </div>
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
                                    <option value="4">4</option>
                                    <option value="8">8</option>
                                    <option value="12">12</option>
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
                onConfirm={() => {
                    if (itemToDelete) {
                        setSpaces(spaces.filter(s => s.id !== itemToDelete.id))
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
    const [spaces, setSpaces] = useState<Space[]>([
        { id: '1', name: 'Financeiro', crewIds: ['1', '2'], connectionIds: [], createdAt: '' },
        { id: '2', name: 'Marketing', crewIds: ['3'], connectionIds: [], createdAt: '' }
    ])
    const [crews, setCrews] = useState<Crew[]>([
        { id: '1', name: 'Salários', spaceId: '1', memberIds: ['1', '2'], connectionIds: [], createdAt: '' },
        { id: '2', name: 'Pagamento', spaceId: '1', memberIds: ['2', '3'], connectionIds: [], createdAt: '' },
        { id: '3', name: 'Campanhas', spaceId: '2', memberIds: ['1'], connectionIds: [], createdAt: '' }
    ])
    const [searchQuery, setSearchQuery] = useState('')
    const [filterSpace, setFilterSpace] = useState<string>('all')
    const [selectedCrew, setSelectedCrew] = useState<string | null>(null)
    const [viewMode, setViewMode] = useState<'list' | 'detail' | 'add'>('list')
    const [deleteModalOpen, setDeleteModalOpen] = useState(false)
    const [itemToDelete, setItemToDelete] = useState<{ id: string; name: string } | null>(null)
    const [currentPage, setCurrentPage] = useState(1)
    const [itemsPerPage, setItemsPerPage] = useState(4)
    const [formData, setFormData] = useState({ name: '', description: '', spaceId: '' })
    
    const filteredCrews = crews.filter(crew => {
        const matchesSearch = crew.name.toLowerCase().includes(searchQuery.toLowerCase())
        const matchesSpace = filterSpace === 'all' || crew.spaceId === filterSpace
        return matchesSearch && matchesSpace
    })
    
    const paginatedCrews = filteredCrews.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage)
    const totalPages = Math.ceil(filteredCrews.length / itemsPerPage)
    
    const stats = {
        total: crews.length,
        totalMembers: new Set(crews.flatMap(c => c.memberIds)).size,
        totalConnections: crews.reduce((sum, c) => sum + c.connectionIds.length, 0),
    }
    
    const handleSaveCrew = () => {
        if (selectedCrew) {
            // Update existing
            setCrews(crews.map(c => 
                c.id === selectedCrew
                    ? {
                        ...c,
                        name: formData.name,
                        description: formData.description || '',
                        spaceId: formData.spaceId,
                        updatedAt: new Date().toISOString()
                    }
                    : c
            ))
        } else {
            // Create new
            const newCrew: Crew = {
                id: Date.now().toString(),
                name: formData.name,
                description: formData.description || '',
                spaceId: formData.spaceId,
                memberIds: [],
                connectionIds: [],
                createdAt: new Date().toISOString()
            }
            setCrews([...crews, newCrew])
            // Update space to include this crew
            setSpaces(spaces.map(s => 
                s.id === formData.spaceId 
                    ? { ...s, crewIds: [...s.crewIds, newCrew.id] }
                    : s
            ))
        }
        
        // Reset
        setViewMode('list')
        setSelectedCrew(null)
        setFormData({ name: '', description: '', spaceId: '' })
    }
    
    const handleCancelCrew = () => {
        setViewMode('list')
        setSelectedCrew(null)
        setFormData({ name: '', description: '', spaceId: '' })
    }
    
    // Initialize form data when editing
    useEffect(() => {
        if (viewMode === 'detail' && selectedCrew) {
            const currentCrew = crews.find(c => c.id === selectedCrew)
            if (currentCrew) {
                setFormData({
                    name: currentCrew.name,
                    description: currentCrew.description || '',
                    spaceId: currentCrew.spaceId
                })
            }
        } else if (viewMode === 'add') {
            setFormData({ name: '', description: '', spaceId: '' })
        }
    }, [viewMode, selectedCrew, crews])
    
    // Render add/edit view
    if (viewMode === 'add' || (viewMode === 'detail' && selectedCrew)) {
        const currentCrew = selectedCrew ? crews.find(c => c.id === selectedCrew) : null
        const isEditing = !!currentCrew
        
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
                                setItemToDelete({ id: selectedCrew!, name: formData.name })
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
                    onConfirm={() => {
                        if (itemToDelete) {
                            setCrews(crews.filter(c => c.id !== itemToDelete.id))
                            setViewMode('list')
                            setSelectedCrew(null)
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
                            "px-4 py-2 rounded-lg text-sm font-medium",
                            "bg-blue-500 hover:bg-blue-600 text-white",
                            "flex items-center gap-2 transition-colors"
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
                {/* Crews List - Rectangular Cards */}
                <div className="space-y-3">
                    {paginatedCrews.map(crew => {
                        const space = spaces.find(s => s.id === crew.spaceId)
                        return (
                            <div
                                key={crew.id}
                                onClick={(e) => {
                                    if ((e.target as HTMLElement).closest('button')) return
                                    setSelectedCrew(crew.id)
                                    setViewMode('detail')
                                }}
                                className={cn(
                                    "relative p-4 rounded-lg border cursor-pointer",
                                    "bg-white dark:bg-gray-800",
                                    "border-gray-200 dark:border-gray-700",
                                    "hover:shadow-md hover:border-blue-300 dark:hover:border-blue-700",
                                    "transition-all duration-200"
                                )}
                            >
                                <div className="flex items-center gap-4">
                                    {/* Icon */}
                                    <div className={cn(
                                        "w-12 h-12 rounded-lg flex items-center justify-center flex-shrink-0 text-white font-bold text-lg",
                                        "bg-purple-500"
                                    )}>
                                        {crew.name.charAt(0).toUpperCase()}
                                    </div>
                                    
                                    {/* Info */}
                                    <div className="flex-1 min-w-0 flex items-center gap-6">
                                        <div className="flex-1">
                                            <div className="flex items-center gap-3 mb-1">
                                                <h3 className="font-semibold text-sm text-foreground">{crew.name}</h3>
                                                <span className="text-xs text-muted-foreground">Crew</span>
                                                {space && (
                                                    <span className="text-xs text-muted-foreground">• {space.name}</span>
                                                )}
                                            </div>
                                            <p className="text-xs text-muted-foreground">{crew.description || 'No description'}</p>
                                        </div>
                                        
                                        {/* Stats Row */}
                                        <div className="flex items-center gap-4">
                                            <div className="text-center">
                                                <p className="text-xs font-semibold text-foreground">{crew.memberIds.length}</p>
                                                <p className="text-[10px] text-muted-foreground">Members</p>
                                            </div>
                                            <div className="text-center">
                                                <p className="text-xs font-semibold text-foreground">{crew.connectionIds.length}</p>
                                                <p className="text-[10px] text-muted-foreground">Connections</p>
                                            </div>
                                        </div>
                                    </div>
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
                                    <option value="4">4</option>
                                    <option value="8">8</option>
                                    <option value="12">12</option>
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
                onConfirm={() => {
                    if (itemToDelete) {
                        setCrews(crews.filter(c => c.id !== itemToDelete.id))
                    }
                }}
                itemName={itemToDelete?.name || ''}
                itemType="crew"
                isDark={isDark}
            />
        </div>
    )
}

