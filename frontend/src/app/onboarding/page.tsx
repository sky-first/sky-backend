"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

// Legacy route: if someone hits /onboarding, immediately send them to the dashboard.
export default function OnboardingPage() {
    const router = useRouter()

    useEffect(() => {
        router.replace("/dashboard")
    }, [router])

    return null
}
