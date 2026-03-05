from typing import Optional, Union

from pydantic import BaseModel


class MetricsTrend(BaseModel):
    value: Optional[str] = None
    isPositive: Optional[bool] = None


class MetricItem(BaseModel):
    value: Union[str, int, float]
    trend: Optional[MetricsTrend] = None


# Global Metrics
class GlobalUsageMetrics(BaseModel):
    totalQueries: MetricItem
    last30Days: MetricItem
    growth: MetricItem
    avgFrequency: MetricItem


class GlobalPerformanceMetrics(BaseModel):
    avgLatency: MetricItem
    slaCompliance: MetricItem
    responseTime: MetricItem


class GlobalEngagementMetrics(BaseModel):
    activeUsers: MetricItem
    topUsersGroup: MetricItem
    recurrenceRate: MetricItem
    satisfactionRate: MetricItem


class GlobalValueGenerationMetrics(BaseModel):
    financialImpact: MetricItem
    hoursSaved: MetricItem
    influencedDecisions: MetricItem
    costAvoided: MetricItem


class GlobalMetricsResponse(BaseModel):
    usage: GlobalUsageMetrics
    performance: GlobalPerformanceMetrics
    engagement: GlobalEngagementMetrics
    valueGeneration: GlobalValueGenerationMetrics


# Connection Metrics
class ConnectionUsageMetrics(BaseModel):
    queriesProcessed: MetricItem
    dataTransferred: MetricItem
    avgSyncFrequency: MetricItem


class ConnectionValueMapMetrics(BaseModel):
    supportedProcesses: MetricItem
    dependentKpis: MetricItem


class ConnectionReliabilityMetrics(BaseModel):
    syncFailures: MetricItem
    avgExecTime: MetricItem
    slaMaintenance: MetricItem


class ConnectionMetricsResponse(BaseModel):
    usage: ConnectionUsageMetrics
    valueMap: ConnectionValueMapMetrics
    reliability: ConnectionReliabilityMetrics


# Space Metrics
class SpaceUsageVolumeMetrics(BaseModel):
    activityPerSpace: MetricItem
    avgEngagement: MetricItem
    interactionVolume: MetricItem


class SpaceNetworkHealthMetrics(BaseModel):
    networkGrowth: MetricItem
    crossCollaboration: MetricItem


class SpaceMetricsResponse(BaseModel):
    usageVolume: SpaceUsageVolumeMetrics
    networkHealth: SpaceNetworkHealthMetrics


# Crew Metrics
class CrewEngagementMetrics(BaseModel):
    usageFrequency: MetricItem
    activeSessions: MetricItem


class CrewPerformanceMetrics(BaseModel):
    avgResponseTime: MetricItem


class CrewMetricsResponse(BaseModel):
    engagement: CrewEngagementMetrics
    performance: CrewPerformanceMetrics


# User Metrics
class UserIndividualPatternsMetrics(BaseModel):
    queriesPerPeriod: MetricItem
    recurrence: MetricItem
    satisfactionScore: MetricItem


class UserMetricsResponse(BaseModel):
    individualPatterns: UserIndividualPatternsMetrics


# AI Metrics
class AiEngineEffectivenessMetrics(BaseModel):
    perceivedAccuracy: MetricItem
    correctionsMade: MetricItem
    insightAcceptanceRate: MetricItem
    averageLatency: MetricItem
    estResponseConfidence: MetricItem


class AiMetricsResponse(BaseModel):
    engineEffectiveness: AiEngineEffectivenessMetrics
