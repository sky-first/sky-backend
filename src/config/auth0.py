"""Auth0 and SSO provider configuration."""

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Auth0Settings(BaseSettings):
    """Auth0 and SSO provider settings."""

    model_config = SettingsConfigDict(
        env_file=[".env.local", ".env", "../deploy/.env"],
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Auth0 Core Configuration
    AUTH0_DOMAIN: str = Field(
        default="",
        description="Auth0 domain (e.g., your-tenant.auth0.com)",
    )
    AUTH0_CLIENT_ID: str = Field(
        default="",
        description="Auth0 client ID",
    )
    AUTH0_CLIENT_SECRET: str = Field(
        default="",
        description="Auth0 client secret",
    )
    AUTH0_AUDIENCE: str = Field(
        default="",
        description="Auth0 API audience/identifier",
    )
    AUTH0_ALGORITHM: str = Field(
        default="RS256",
        description="Auth0 JWT algorithm (RS256 or HS256)",
    )

    # Google OAuth Configuration
    GOOGLE_CLIENT_ID: Optional[str] = Field(
        default=None,
        description="Google OAuth client ID",
    )
    GOOGLE_CLIENT_SECRET: Optional[str] = Field(
        default=None,
        description="Google OAuth client secret",
    )
    GOOGLE_REDIRECT_URI: Optional[str] = Field(
        default=None,
        description="Google OAuth redirect URI",
    )

    # Azure AD Configuration
    AZURE_CLIENT_ID: Optional[str] = Field(
        default=None,
        description="Azure AD application (client) ID",
    )
    AZURE_CLIENT_SECRET: Optional[str] = Field(
        default=None,
        description="Azure AD client secret",
    )
    AZURE_TENANT_ID: Optional[str] = Field(
        default=None,
        description="Azure AD tenant ID",
    )
    AZURE_REDIRECT_URI: Optional[str] = Field(
        default=None,
        description="Azure AD redirect URI",
    )

    # Okta Configuration
    OKTA_DOMAIN: Optional[str] = Field(
        default=None,
        description="Okta domain (e.g., your-tenant.okta.com)",
    )
    OKTA_CLIENT_ID: Optional[str] = Field(
        default=None,
        description="Okta client ID",
    )
    OKTA_CLIENT_SECRET: Optional[str] = Field(
        default=None,
        description="Okta client secret",
    )
    OKTA_REDIRECT_URI: Optional[str] = Field(
        default=None,
        description="Okta redirect URI",
    )

    # Feature Flags
    ENABLE_SSO: bool = Field(
        default=True,
        description="Enable SSO authentication",
    )
    ENABLE_INVITE_LOGIN: bool = Field(
        default=True,
        description="Enable invite-based login",
    )
    ENABLE_AUTH0: bool = Field(
        default=True,
        description="Enable Auth0 authentication",
    )

    @property
    def is_auth0_enabled(self) -> bool:
        """Check if Auth0 is properly configured."""
        return (
            self.ENABLE_AUTH0
            and bool(self.AUTH0_DOMAIN)
            and bool(self.AUTH0_CLIENT_ID)
            and bool(self.AUTH0_CLIENT_SECRET)
        )

    @property
    def is_google_enabled(self) -> bool:
        """Check if Google SSO is properly configured."""
        return self.ENABLE_SSO and bool(self.GOOGLE_CLIENT_ID) and bool(self.GOOGLE_CLIENT_SECRET)

    @property
    def is_azure_enabled(self) -> bool:
        """Check if Azure AD SSO is properly configured."""
        return (
            self.ENABLE_SSO
            and bool(self.AZURE_CLIENT_ID)
            and bool(self.AZURE_CLIENT_SECRET)
            and bool(self.AZURE_TENANT_ID)
        )

    @property
    def is_okta_enabled(self) -> bool:
        """Check if Okta SSO is properly configured."""
        return (
            self.ENABLE_SSO
            and bool(self.OKTA_DOMAIN)
            and bool(self.OKTA_CLIENT_ID)
            and bool(self.OKTA_CLIENT_SECRET)
        )

    @property
    def auth0_jwks_url(self) -> str:
        """Get Auth0 JWKS URL."""
        if not self.AUTH0_DOMAIN:
            raise ValueError("AUTH0_DOMAIN not configured")
        return f"https://{self.AUTH0_DOMAIN}/.well-known/jwks.json"

    @property
    def google_authorization_url(self) -> str:
        """Get Google OAuth authorization URL."""
        return "https://accounts.google.com/o/oauth2/v2/auth"

    @property
    def google_token_url(self) -> str:
        """Get Google OAuth token URL."""
        return "https://oauth2.googleapis.com/token"

    @property
    def azure_authorization_url(self) -> str:
        """Get Azure AD authorization URL."""
        if not self.AZURE_TENANT_ID:
            raise ValueError("AZURE_TENANT_ID not configured")
        return f"https://login.microsoftonline.com/{self.AZURE_TENANT_ID}/oauth2/v2.0/authorize"

    @property
    def azure_token_url(self) -> str:
        """Get Azure AD token URL."""
        if not self.AZURE_TENANT_ID:
            raise ValueError("AZURE_TENANT_ID not configured")
        return f"https://login.microsoftonline.com/{self.AZURE_TENANT_ID}/oauth2/v2.0/token"

    @property
    def okta_authorization_url(self) -> str:
        """Get Okta authorization URL."""
        if not self.OKTA_DOMAIN:
            raise ValueError("OKTA_DOMAIN not configured")
        return f"https://{self.OKTA_DOMAIN}/oauth2/v1/authorize"

    @property
    def okta_token_url(self) -> str:
        """Get Okta token URL."""
        if not self.OKTA_DOMAIN:
            raise ValueError("OKTA_DOMAIN not configured")
        return f"https://{self.OKTA_DOMAIN}/oauth2/v1/token"


# Global Auth0 settings instance
def get_auth0_settings() -> Auth0Settings:
    """Get Auth0 settings instance."""
    return Auth0Settings()


auth0_settings = get_auth0_settings()
