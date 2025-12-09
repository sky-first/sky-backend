import { create } from 'zustand'
import { usersApi, type User, type UserCreate, type UserUpdate, type UserPermissions, type UserPermissionsUpdate, type UserInvite } from '@/lib/api/users'

export interface UsersState {
    users: User[]
    currentUser: User | null
    isLoading: boolean
    error: string | null
    
    // User permissions (per user)
    userPermissions: Record<string, UserPermissions>
    
    // Actions
    fetchUsers: (params?: { skip?: number; limit?: number }) => Promise<void>
    fetchUser: (userId: string) => Promise<User>
    createUser: (data: UserCreate) => Promise<User>
    updateUser: (userId: string, updates: UserUpdate) => Promise<User>
    deleteUser: (userId: string) => Promise<void>
    setCurrentUser: (user: User | null) => void
    
    // Permissions
    fetchUserPermissions: (userId: string) => Promise<void>
    updateUserPermissions: (userId: string, data: UserPermissionsUpdate) => Promise<UserPermissions>
    
    // Invites
    inviteUser: (userId: string, data: UserInvite) => Promise<void>
}

export const useUsersStore = create<UsersState>()(
    (set, get) => ({
        users: [],
        currentUser: null,
        isLoading: false,
        error: null,
        userPermissions: {},

        fetchUsers: async (params) => {
            set({ isLoading: true, error: null })
            try {
                const users = await usersApi.listUsers(params)
                set({ 
                    users,
                    isLoading: false 
                })
            } catch (error) {
                console.error('Error fetching users:', error)
                set({ 
                    error: error instanceof Error ? error.message : 'Failed to fetch users',
                    isLoading: false 
                })
            }
        },

        fetchUser: async (userId) => {
            set({ isLoading: true, error: null })
            try {
                const user = await usersApi.getUser(userId)
                set((state) => ({
                    users: state.users.some(u => u.id === userId)
                        ? state.users.map(u => u.id === userId ? user : u)
                        : [...state.users, user],
                    currentUser: user,
                    isLoading: false,
                }))
                return user
            } catch (error) {
                console.error('Error fetching user:', error)
                set({ 
                    error: error instanceof Error ? error.message : 'Failed to fetch user',
                    isLoading: false 
                })
                throw error
            }
        },

        createUser: async (data) => {
            set({ isLoading: true, error: null })
            try {
                const user = await usersApi.createUser(data)
                set((state) => ({
                    users: [...state.users, user],
                    currentUser: user, // Set as current
                    isLoading: false,
                }))
                return user
            } catch (error) {
                console.error('Error creating user:', error)
                set({ 
                    error: error instanceof Error ? error.message : 'Failed to create user',
                    isLoading: false 
                })
                throw error
            }
        },

        updateUser: async (userId, updates) => {
            set({ isLoading: true, error: null })
            try {
                const user = await usersApi.updateUser(userId, updates)
                set((state) => ({
                    users: state.users.map((u) =>
                        u.id === userId ? user : u
                    ),
                    currentUser: state.currentUser?.id === userId
                        ? user
                        : state.currentUser,
                    isLoading: false,
                }))
                return user
            } catch (error) {
                console.error('Error updating user:', error)
                set({ 
                    error: error instanceof Error ? error.message : 'Failed to update user',
                    isLoading: false 
                })
                throw error
            }
        },

        deleteUser: async (userId) => {
            set({ isLoading: true, error: null })
            try {
                await usersApi.deleteUser(userId)
                set((state) => ({
                    users: state.users.filter((u) => u.id !== userId),
                    currentUser: state.currentUser?.id === userId
                        ? null
                        : state.currentUser,
                    // Clean up related data
                    userPermissions: Object.fromEntries(
                        Object.entries(state.userPermissions).filter(([key]) => key !== userId)
                    ),
                    isLoading: false,
                }))
            } catch (error) {
                console.error('Error deleting user:', error)
                set({ 
                    error: error instanceof Error ? error.message : 'Failed to delete user',
                    isLoading: false 
                })
                throw error
            }
        },

        setCurrentUser: (user) => {
            set({ currentUser: user })
        },

        fetchUserPermissions: async (userId) => {
            set({ isLoading: true, error: null })
            try {
                const permissions = await usersApi.getUserPermissions(userId)
                set((state) => ({
                    userPermissions: {
                        ...state.userPermissions,
                        [userId]: permissions,
                    },
                    isLoading: false,
                }))
            } catch (error) {
                console.error('Error fetching user permissions:', error)
                set({ 
                    error: error instanceof Error ? error.message : 'Failed to fetch user permissions',
                    isLoading: false 
                })
            }
        },

        updateUserPermissions: async (userId, data) => {
            set({ isLoading: true, error: null })
            try {
                const permissions = await usersApi.updateUserPermissions(userId, data)
                set((state) => ({
                    userPermissions: {
                        ...state.userPermissions,
                        [userId]: permissions,
                    },
                    // Also update the user's role in the users list
                    users: state.users.map(u =>
                        u.id === userId ? { ...u, role: permissions.role as 'admin' | 'user' | 'viewer' } : u
                    ),
                    currentUser: state.currentUser?.id === userId
                        ? { ...state.currentUser, role: permissions.role as 'admin' | 'user' | 'viewer' }
                        : state.currentUser,
                    isLoading: false,
                }))
                return permissions
            } catch (error) {
                console.error('Error updating user permissions:', error)
                set({ 
                    error: error instanceof Error ? error.message : 'Failed to update user permissions',
                    isLoading: false 
                })
                throw error
            }
        },

        inviteUser: async (userId, data) => {
            set({ isLoading: true, error: null })
            try {
                await usersApi.inviteUser(userId, data)
                set({ isLoading: false })
            } catch (error) {
                console.error('Error inviting user:', error)
                set({ 
                    error: error instanceof Error ? error.message : 'Failed to invite user',
                    isLoading: false 
                })
                throw error
            }
        },
    })
)

