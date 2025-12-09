import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { authApi, type UserResponse } from '@/lib/api/auth'

interface UserState {
    isAuthenticated: boolean
    user: {
        id: string
        name: string
        email: string
        avatar?: string
        role: string
    } | null
    onboardingStep: number
    hasCompletedOnboarding: boolean
    selectedDomain: string | null
    isLoading: boolean
    // Actions
    login: (userData: Pick<UserResponse, 'id' | 'name' | 'email' | 'avatar' | 'role'>, onboardingStep?: number, hasCompletedOnboarding?: boolean) => void
    logout: () => Promise<void>
    setDomain: (domain: string) => void
    completeOnboarding: () => void
    setOnboardingStep: (step: number) => void
    checkSession: () => Promise<void>
    setLoading: (loading: boolean) => void
}

export const useUserStore = create<UserState>()(
    persist(
        (set, get) => ({
            isAuthenticated: false,
            user: null,
            onboardingStep: 0,
            hasCompletedOnboarding: false,
            selectedDomain: null,
            isLoading: false,
            
            login: (userData, onboardingStep = 0, hasCompletedOnboarding = false) => set({
                isAuthenticated: true,
                user: {
                    id: userData.id,
                    name: userData.name,
                    email: userData.email,
                    avatar: userData.avatar,
                    role: userData.role,
                },
                onboardingStep,
                hasCompletedOnboarding,
            }),
            
            logout: async () => {
                try {
                    await authApi.logout()
                } catch (error) {
                    console.error('Logout error:', error)
                } finally {
                    set({ 
                        isAuthenticated: false, 
                        user: null,
                        onboardingStep: 0,
                        hasCompletedOnboarding: false,
                    })
                }
            },
            
            setDomain: (domain) => set({ selectedDomain: domain }),
            
            completeOnboarding: () => set({ hasCompletedOnboarding: true }),
            
            setOnboardingStep: (step) => set({ onboardingStep: step }),
            
            checkSession: async () => {
                const { isLoading } = get()
                if (isLoading) return
                
                set({ isLoading: true })
                try {
                    const user = await authApi.getSession()
                    set({
                        isAuthenticated: true,
                        user: {
                            id: user.id,
                            name: user.name,
                            email: user.email,
                            avatar: user.avatar,
                            role: user.role,
                        },
                        onboardingStep: user.onboarding_step || 0,
                        hasCompletedOnboarding: user.has_completed_onboarding || false,
                    })
                } catch (error) {
                    // Session invalid, clear state
                    set({ 
                        isAuthenticated: false, 
                        user: null,
                        onboardingStep: 0,
                        hasCompletedOnboarding: false,
                    })
                } finally {
                    set({ isLoading: false })
                }
            },
            
            setLoading: (loading) => set({ isLoading: loading }),
        }),
        {
            name: 'user-storage',
        }
    )
)
