"use client"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { useUserStore } from "@/store/user-store"
import { authApi } from "@/lib/api/auth"

type Star = { id: number; top: number; left: number; opacity: number; size: number; delay: number; duration: number }
type Comet = { id: number; left: number; delay: number; duration: number; topOffset: number }

export default function LoginPage() {
    const [email, setEmail] = useState("")
    const [password, setPassword] = useState("")
    const [isLoading, setIsLoading] = useState(false)
    const [stars, setStars] = useState<Star[]>([])
    const [comets, setComets] = useState<Comet[]>([])

    const router = useRouter()

    useEffect(() => {
        // Static stars scattered across the screen
        const generatedStars: Star[] = Array.from({ length: 180 }, (_, i) => ({
            id: i,
            top: Math.random() * 100,
            left: Math.random() * 100,
            opacity: 0.3 + Math.random() * 0.7,
            size: 0.5 + Math.random() * 1.5,
            delay: Math.random() * 4,
            duration: 3 + Math.random() * 4,
        }))

        // Medium white comets falling diagonally
        const generatedComets: Comet[] = Array.from({ length: 7 }, (_, i) => ({
            id: i,
            left: -10 + Math.random() * 120, // pode começar um pouco fora
            delay: Math.random() * 8,
            duration: 3.5 + Math.random() * 4,
            topOffset: Math.random() * 30, // variação de altura inicial
        }))

        setStars(generatedStars)
        setComets(generatedComets)
    }, [])

    const handleLogin = async (e: React.FormEvent) => {
        e.preventDefault()
        setIsLoading(true)
        
        try {
            console.log("[Login] Attempting login for:", email)
            console.log("[Login] API URL:", process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1")
            const response = await authApi.login({ email, password })
            console.log("[Login] Login successful:", { userId: response.user.id, email: response.user.email })
            
            // Verify response structure
            if (!response.access_token || !response.refresh_token) {
                throw new Error("Invalid response from server: missing tokens")
            }
            
            if (!response.user || !response.user.id) {
                throw new Error("Invalid response from server: missing user data")
            }
            
            // Update user store with real data
            useUserStore.getState().login(
                {
                    id: response.user.id,
                    name: response.user.name,
                    email: response.user.email,
                    avatar: response.user.avatar,
                    role: response.user.role,
                },
                response.user.onboarding_step || 0,
                response.user.has_completed_onboarding || false
            )
            
            console.log("[Login] User store updated, redirecting to dashboard")
            router.push("/dashboard")
        } catch (error) {
            console.error("Login error:", error)
            let errorMessage = "Login failed. Please try again."
            
            if (error instanceof Error) {
                errorMessage = error.message
                // Try to extract a cleaner error message
                if (errorMessage.includes("401") || errorMessage.includes("Unauthorized") || errorMessage.includes("Invalid email or password")) {
                    errorMessage = "Invalid email or password. Please check your credentials."
                } else if (errorMessage.includes("Network") || errorMessage.includes("fetch") || errorMessage.includes("Failed to fetch") || errorMessage.includes("Unable to connect")) {
                    errorMessage = "Unable to connect to the server. Please check if the backend is running on port 8001."
                } else if (errorMessage.includes("CORS")) {
                    errorMessage = "CORS error. Please check backend configuration."
                } else if (errorMessage.includes("404")) {
                    errorMessage = "API endpoint not found. Please check if the backend is running and the API URL is correct."
                } else if (errorMessage.includes("Load failed")) {
                    errorMessage = "Failed to load data. Please check if the backend is running on port 8001 and accessible."
                }
            }
            
            alert(errorMessage)
        } finally {
            setIsLoading(false)
        }
    }

    return (
        <div className="login-root min-h-screen w-full relative flex items-center justify-center overflow-hidden bg-[#050509]">
            <style jsx>{`
                /* Gently twinkling stars */
                @keyframes twinkle {
                    0%,
                    100% {
                        opacity: 0.3;
                        transform: scale(0.9);
                    }
                    50% {
                        opacity: 1;
                        transform: scale(1.15);
                    }
                }

                /* Comets falling diagonally */
                @keyframes meteor {
                    0% {
                        transform: rotate(215deg) translateX(0);
                        opacity: 0;
                    }
                    10% {
                        opacity: 1;
                    }
                    80% {
                        opacity: 1;
                    }
                    100% {
                        transform: rotate(215deg) translateX(-120vh);
                        opacity: 0;
                    }
                }

                /* Nebulae / other galaxies */
                @keyframes float-soft {
                    0%,
                    100% {
                        transform: translate(0, 0) scale(1);
                    }
                    50% {
                        transform: translate(-30px, 20px) scale(1.05);
                    }
                }

                .star {
                    position: absolute;
                    background: white;
                    border-radius: 999px;
                    box-shadow: 0 0 4px rgba(255, 255, 255, 0.7);
                    animation-name: twinkle;
                    animation-timing-function: ease-in-out;
                    animation-iteration-count: infinite;
                }

                .comet {
                    position: absolute;
                    width: 3px;
                    height: 3px;
                    background: #ffffff;
                    border-radius: 999px;
                    box-shadow: 0 0 8px rgba(255, 255, 255, 0.8);
                    animation-name: meteor;
                    animation-timing-function: linear;
                    animation-iteration-count: infinite;
                }

                .comet::before {
                    content: "";
                    position: absolute;
                    top: 50%;
                    transform: translateY(-50%);
                    right: 0;
                    width: 160px;
                    height: 2px;
                    background: linear-gradient(90deg, rgba(255, 255, 255, 0.9), transparent);
                    border-radius: 999px;
                }

                .milky-band {
                    position: absolute;
                    top: -40%;
                    left: -20%;
                    width: 160%;
                    height: 180%;
                    background: radial-gradient(
                            ellipse at center,
                            rgba(148, 163, 184, 0.25),
                            transparent 70%
                        );
                    transform: rotate(-30deg);
                    opacity: 0.35;
                    pointer-events: none;
                }

                .galaxy-blue {
                    position: absolute;
                    width: 40vw;
                    height: 40vw;
                    border-radius: 999px;
                    background: radial-gradient(circle at center, rgba(59, 130, 246, 0.2), transparent 70%);
                    filter: blur(70px);
                    opacity: 0.7;
                    animation: float-soft 18s ease-in-out infinite;
                    pointer-events: none;
                }

                .galaxy-cyan {
                    position: absolute;
                    width: 32vw;
                    height: 32vw;
                    border-radius: 999px;
                    background: radial-gradient(circle at center, rgba(34, 211, 238, 0.18), transparent 70%);
                    filter: blur(65px);
                    opacity: 0.6;
                    animation: float-soft 22s ease-in-out infinite;
                    pointer-events: none;
                }

                /* -------- Light mode overrides -------- */
                :global(body:not(.dark)) .login-root {
                    background: radial-gradient(circle at top, #e0f2ff 0, #f9fafb 40%, #e5e7eb 100%);
                }

                :global(body:not(.dark)) .login-root .milky-band,
                :global(body:not(.dark)) .login-root .galaxy-blue,
                :global(body:not(.dark)) .login-root .galaxy-cyan,
                :global(body:not(.dark)) .login-root .star,
                :global(body:not(.dark)) .login-root .comet {
                    opacity: 0.08;
                    filter: blur(1px);
                }

                :global(body:not(.dark)) .login-root .login-card {
                    background: rgba(255, 255, 255, 0.95);
                    border-color: rgba(148, 163, 184, 0.4);
                    box-shadow: 0 25px 60px rgba(15, 23, 42, 0.25);
                }

                :global(body:not(.dark)) .login-root .login-title {
                    color: #020617;
                }

                :global(body:not(.dark)) .login-root .login-subtitle {
                    color: #475569;
                }

                :global(body:not(.dark)) .login-root .login-input {
                    background: #ffffff;
                    color: #020617;
                    border-color: rgba(148, 163, 184, 0.6);
                }

                :global(body:not(.dark)) .login-root .login-input::placeholder {
                    color: #9ca3af;
                }

                :global(body:not(.dark)) .login-root .login-label {
                    color: #0f172a;
                }

                :global(body:not(.dark)) .login-root .login-link {
                    color: #64748b;
                }

                :global(body:not(.dark)) .login-root .login-link:hover {
                    color: #0f172a;
                }

                :global(body:not(.dark)) .login-root .login-button-bg {
                    background: linear-gradient(to right, #0f172a, #1d4ed8, #38bdf8);
                }

                :global(body:not(.dark)) .login-root .login-button-text {
                    color: #f9fafb;
                }
            `}</style>

            {/* Milky Way band */}
            <div className="milky-band" />

            {/* Other blue galaxies */}
            <div className="galaxy-blue top-[5%] right-[-10%]" />
            <div className="galaxy-cyan bottom-[-5%] left-[-5%]" />

            {/* Background stars */}
            <div className="absolute inset-0 z-0">
                {stars.map((star) => (
                    <div
                        key={star.id}
                        className="star"
                        style={{
                            top: `${star.top}%`,
                            left: `${star.left}%`,
                            width: `${star.size}px`,
                            height: `${star.size}px`,
                            opacity: star.opacity,
                            animationDelay: `${star.delay}s`,
                            animationDuration: `${star.duration}s`,
                        }}
                    />
                ))}
            </div>

            {/* White comets falling */}
            <div className="absolute inset-0 z-0 pointer-events-none">
                {comets.map((comet) => (
                    <div
                        key={comet.id}
                        className="comet"
                        style={{
                            left: `${comet.left}%`,
                            top: `-${comet.topOffset}%`,
                            animationDelay: `${comet.delay}s`,
                            animationDuration: `${comet.duration}s`,
                        }}
                    />
                ))}
            </div>

            {/* Centered login card */}
            <div className="relative z-10 w-full max-w-[420px] px-6">
                <div className="login-card relative bg-black/40 backdrop-blur-2xl border border-white/10 rounded-3xl shadow-[0_0_40px_rgba(0,0,0,0.8)] px-8 py-10">
                    {/* brilho superior */}
                    <div className="absolute inset-x-0 top-0 h-20 bg-gradient-to-b from-white/10 to-transparent rounded-t-3xl pointer-events-none" />

                    <div className="relative">
                        <h1 className="login-title text-5xl font-sans font-normal text-white text-center mb-3">
                            Login
                        </h1>
                        <p className="login-subtitle text-center text-gray-400 text-sm mb-10">
                            Access your dashboard and keep navigating through the data galaxy.
                        </p>

                        <form onSubmit={handleLogin} className="space-y-6">
                            <div className="space-y-2">
                                <label
                                    htmlFor="email"
                                    className="login-label text-gray-300 text-xs uppercase tracking-[0.18em] font-medium ml-1"
                                >
                                    Email
                                </label>
                                <input
                                    id="email"
                                    type="email"
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    required
                                    placeholder="your@email.com"
                                    className="login-input relative w-full px-3 py-2.5 text-sm bg-[#050512]/95 text-white rounded-xl border border-white/10 focus:outline-none focus:border-white/30 placeholder:text-gray-600"
                                />
                            </div>

                            <div className="space-y-2">
                                <label
                                    htmlFor="password"
                                    className="login-label text-gray-300 text-xs uppercase tracking-[0.18em] font-medium ml-1"
                                >
                                    Password
                                </label>
                                <input
                                    id="password"
                                    type="password"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    required
                                    placeholder="••••••••"
                                    className="login-input relative w-full px-3 py-2.5 text-sm bg-[#050512]/95 text-white rounded-xl border border-white/10 focus:outline-none focus:border-white/30 placeholder:text-gray-600"
                                />
                                <div className="text-right mt-1">
                                    <a
                                        href="#"
                                        className="login-link text-xs text-gray-400 hover:text-white transition-colors"
                                    >
                                        Forgot password
                                    </a>
                                </div>
                            </div>

                            {/* Primary submit button styled similar to light model */}
                            <button
                                type="submit"
                                disabled={isLoading}
                                className="w-full mt-2 rounded-lg bg-slate-900 text-white text-sm font-medium py-3 disabled:opacity-60 disabled:cursor-not-allowed hover:bg-slate-800 transition-colors"
                            >
                                {isLoading ? "Signing in..." : "Sign in"}
                            </button>
                        </form>
                    </div>
                </div>
            </div>
        </div>
    )
}