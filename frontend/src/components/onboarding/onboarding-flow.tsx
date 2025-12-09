"use client"

import { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { useUserStore } from "@/store/user-store"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import {
    Briefcase,
    TrendingUp,
    Truck,
    BarChart3,
    Cpu,
    CheckCircle2,
    ArrowRight,
    LayoutDashboard
} from "lucide-react"
import { cn } from "@/lib/utils"

const DOMAINS = [
    { id: "finance", name: "Finance", icon: TrendingUp, description: "Revenue, Cash Flow, Profitability" },
    { id: "commercial", name: "Commercial", icon: Briefcase, description: "Sales Pipeline, CRM, Leads" },
    { id: "logistics", name: "Logistics", icon: Truck, description: "Supply Chain, Inventory, Fleet" },
    { id: "analysis", name: "Analysis", icon: BarChart3, description: "Data Science, BI, Reporting" },
    { id: "it", name: "IT", icon: Cpu, description: "Infrastructure, Systems, DevOps" },
]

const TEMPLATES = {
    finance: [
        { id: "revenue", name: "Revenue Overview", description: "Track MRR, ARR, and Churn" },
        { id: "profit", name: "Profitability Analysis", description: "Margins, EBITDA, and Expenses" },
        { id: "cashflow", name: "Cash Flow Dashboard", description: "Inflow, Outflow, and Burn Rate" },
    ],
    commercial: [
        { id: "pipeline", name: "Sales Pipeline", description: "Deal stages and conversion rates" },
        { id: "performance", name: "Team Performance", description: "Quotas and activity tracking" },
    ],
    logistics: [
        { id: "inventory", name: "Inventory Management", description: "Stock levels and turnover" },
        { id: "delivery", name: "Delivery Tracking", description: "Fleet status and delivery times" },
    ],
    analysis: [
        { id: "general", name: "General Analytics", description: "Website traffic and user behavior" },
    ],
    it: [
        { id: "system", name: "System Health", description: "Uptime, latency, and errors" },
    ],
}

export function OnboardingFlow() {
    const [step, setStep] = useState(1)
    const [selectedDomain, setSelectedDomain] = useState<string | null>(null)
    const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null)
    const [workspaceName, setWorkspaceName] = useState("")
    const { setDomain, completeOnboarding } = useUserStore()
    const router = useRouter()

    const handleDomainSelect = (domainId: string) => {
        setSelectedDomain(domainId)
        setDomain(domainId)
    }

    const handleNext = () => {
        if (step === 1 && selectedDomain) setStep(2)
        else if (step === 2 && selectedTemplate) setStep(3)
        else if (step === 3) handleFinish()
    }

    const handleFinish = async () => {
        completeOnboarding()
        // Simulate setup delay
        await new Promise(resolve => setTimeout(resolve, 1500))
        router.push("/dashboard")
    }

    return (
        <div className="w-full max-w-4xl mx-auto">
            <div className="mb-8 text-center">
                <h1 className="text-3xl font-bold mb-2">Let's set up your workspace</h1>
                <p className="text-muted-foreground">Step {step} of 3</p>
                <div className="w-full h-2 bg-secondary mt-4 rounded-full overflow-hidden max-w-md mx-auto">
                    <motion.div
                        className="h-full bg-primary"
                        initial={{ width: "0%" }}
                        animate={{ width: `${(step / 3) * 100}%` }}
                    />
                </div>
            </div>

            <AnimatePresence mode="wait">
                {step === 1 && (
                    <motion.div
                        key="step1"
                        initial={{ opacity: 0, x: 20 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: -20 }}
                        className="space-y-6"
                    >
                        <div className="text-center mb-8">
                            <h2 className="text-xl font-semibold">Choose your department</h2>
                            <p className="text-sm text-muted-foreground">We'll tailor the experience for you</p>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            {DOMAINS.map((domain) => (
                                <Card
                                    key={domain.id}
                                    className={cn(
                                        "cursor-pointer transition-all hover:border-primary hover:shadow-lg",
                                        selectedDomain === domain.id ? "border-primary ring-2 ring-primary/20" : ""
                                    )}
                                    onClick={() => handleDomainSelect(domain.id)}
                                >
                                    <CardHeader>
                                        <domain.icon className="w-8 h-8 text-primary mb-2" />
                                        <CardTitle className="text-lg">{domain.name}</CardTitle>
                                        <CardDescription>{domain.description}</CardDescription>
                                    </CardHeader>
                                </Card>
                            ))}
                        </div>
                    </motion.div>
                )}

                {step === 2 && selectedDomain && (
                    <motion.div
                        key="step2"
                        initial={{ opacity: 0, x: 20 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: -20 }}
                        className="space-y-6"
                    >
                        <div className="text-center mb-8">
                            <h2 className="text-xl font-semibold">Select a starting template</h2>
                            <p className="text-sm text-muted-foreground">Or start from scratch later</p>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <Card
                                className={cn(
                                    "cursor-pointer transition-all hover:border-primary",
                                    selectedTemplate === "blank" ? "border-primary ring-2 ring-primary/20" : ""
                                )}
                                onClick={() => setSelectedTemplate("blank")}
                            >
                                <CardHeader>
                                    <LayoutDashboard className="w-8 h-8 text-muted-foreground mb-2" />
                                    <CardTitle className="text-lg">Blank Canvas</CardTitle>
                                    <CardDescription>Start with an empty board</CardDescription>
                                </CardHeader>
                            </Card>
                            {TEMPLATES[selectedDomain as keyof typeof TEMPLATES]?.map((template) => (
                                <Card
                                    key={template.id}
                                    className={cn(
                                        "cursor-pointer transition-all hover:border-primary",
                                        selectedTemplate === template.id ? "border-primary ring-2 ring-primary/20" : ""
                                    )}
                                    onClick={() => setSelectedTemplate(template.id)}
                                >
                                    <CardHeader>
                                        <BarChart3 className="w-8 h-8 text-primary mb-2" />
                                        <CardTitle className="text-lg">{template.name}</CardTitle>
                                        <CardDescription>{template.description}</CardDescription>
                                    </CardHeader>
                                </Card>
                            ))}
                        </div>
                    </motion.div>
                )}

                {step === 3 && (
                    <motion.div
                        key="step3"
                        initial={{ opacity: 0, x: 20 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: -20 }}
                        className="space-y-6 max-w-md mx-auto"
                    >
                        <div className="text-center mb-8">
                            <h2 className="text-xl font-semibold">Name your workspace</h2>
                        </div>
                        <Card>
                            <CardContent className="pt-6">
                                <div className="space-y-4">
                                    <div className="space-y-2">
                                        <Label htmlFor="workspace">Workspace Name</Label>
                                        <Input
                                            id="workspace"
                                            placeholder="My Awesome Dashboard"
                                            value={workspaceName}
                                            onChange={(e) => setWorkspaceName(e.target.value)}
                                        />
                                    </div>
                                </div>
                            </CardContent>
                        </Card>
                    </motion.div>
                )}
            </AnimatePresence>

            <div className="mt-8 flex justify-between">
                <Button
                    variant="ghost"
                    onClick={() => setStep(Math.max(1, step - 1))}
                    disabled={step === 1}
                >
                    Back
                </Button>
                <Button
                    onClick={handleNext}
                    disabled={
                        (step === 1 && !selectedDomain) ||
                        (step === 2 && !selectedTemplate)
                    }
                >
                    {step === 3 ? "Finish Setup" : "Continue"} <ArrowRight className="ml-2 w-4 h-4" />
                </Button>
            </div>
        </div>
    )
}
