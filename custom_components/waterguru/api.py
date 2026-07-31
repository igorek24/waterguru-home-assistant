"""Async client for the WaterGuru cloud API.

WaterGuru has no public API. The mobile app authenticates against AWS
Cognito (SRP) and then invokes a Lambda function directly with SigV4
signed requests. This client reproduces that flow:

    1. Cognito user pool SRP login          -> id/access/refresh tokens
    2. Cognito identity pool                -> temporary AWS credentials
    3. SigV4 POST to prod-getDashboardView  -> the dashboard payload

Only the SRP maths comes from `pycognito` (which ships with Home
Assistant via hass-nabucasa); every network call is done with aiohttp so
nothing blocks the event loop. Unlike the reference implementations this
client refreshes tokens instead of re-authenticating on every poll.
"""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hashlib
import hmac
import json
import logging
from typing import Any
from urllib.parse import quote

import aiohttp

_LOGGER = logging.getLogger(__name__)

REGION = "us-west-2"
USER_POOL_ID = "us-west-2_icsnuWQWw"
CLIENT_ID = "7pk5du7fitqb419oabb3r92lni"
IDENTITY_POOL_ID = "us-west-2:691e3287-5776-40f2-a502-759de65a8f1c"
IDP_KEY = f"cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}"

IDP_URL = f"https://cognito-idp.{REGION}.amazonaws.com/"
IDENTITY_URL = f"https://cognito-identity.{REGION}.amazonaws.com/"
LAMBDA_HOST = f"lambda.{REGION}.amazonaws.com"
LAMBDA_FUNCTION = "prod-getDashboardView"
LAMBDA_PATH = f"/2015-03-31/functions/{LAMBDA_FUNCTION}/invocations"

CLIENT_TYPE = "WEB_APP"
CLIENT_VERSION = "0.2.3"

# refresh a little before the real expiry
TOKEN_MARGIN = dt.timedelta(minutes=5)


class WaterGuruError(Exception):
    """Base error."""


class WaterGuruAuthError(WaterGuruError):
    """Credentials were rejected."""


class WaterGuruConnectionError(WaterGuruError):
    """The service could not be reached."""


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _decode_jwt_claims(token: str) -> dict[str, Any]:
    """Read the (already server-verified) claims out of a JWT."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError) as err:
        raise WaterGuruAuthError(f"Malformed identity token: {err}") from err


def _sigv4_headers(
    *,
    access_key: str,
    secret_key: str,
    session_token: str,
    host: str,
    path: str,
    body: bytes,
    service: str = "lambda",
    region: str = REGION,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build AWS SigV4 headers for a POST request."""
    now = _utcnow()
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    headers = {
        "content-type": "application/x-amz-json-1.0",
        "host": host,
        "x-amz-date": amz_date,
        "x-amz-security-token": session_token,
    }
    if extra_headers:
        headers.update({k.lower(): v for k, v in extra_headers.items()})

    signed_headers = ";".join(sorted(headers))
    canonical_headers = "".join(
        f"{key}:{headers[key].strip()}\n" for key in sorted(headers)
    )
    payload_hash = hashlib.sha256(body).hexdigest()
    canonical_request = "\n".join(
        [
            "POST",
            quote(path, safe="/-_.~"),
            "",
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )

    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )

    def _sign(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    key = _sign(f"AWS4{secret_key}".encode(), date_stamp)
    key = _sign(key, region)
    key = _sign(key, service)
    key = _sign(key, "aws4_request")
    signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()

    headers["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return headers


class WaterGuruClient:
    """Talks to the WaterGuru cloud."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password

        self._id_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expires: dt.datetime | None = None
        self._user_id: str | None = None

        self._identity_id: str | None = None
        self._credentials: dict[str, Any] | None = None
        self._credentials_expire: dt.datetime | None = None

        self._lock = asyncio.Lock()

    @property
    def user_id(self) -> str | None:
        return self._user_id

    # -- low level ----------------------------------------------------------

    async def _idp_call(self, target: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._aws_json_call(IDP_URL, target, payload)

    async def _identity_call(
        self, target: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._aws_json_call(IDENTITY_URL, target, payload)

    async def _aws_json_call(
        self, url: str, target: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": target,
        }
        try:
            async with self._session.post(
                url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                text = await resp.text()
                if resp.status != 200:
                    try:
                        err = json.loads(text)
                        kind = err.get("__type", "")
                        message = err.get("message", text)
                    except ValueError:
                        kind, message = "", text
                    if any(
                        marker in kind
                        for marker in (
                            "NotAuthorized",
                            "UserNotFound",
                            "InvalidParameter",
                            "ResourceNotFound",
                        )
                    ):
                        raise WaterGuruAuthError(message)
                    raise WaterGuruConnectionError(f"{target} failed: {message}")
                return json.loads(text)
        except aiohttp.ClientError as err:
            raise WaterGuruConnectionError(f"{target} failed: {err}") from err
        except asyncio.TimeoutError as err:
            raise WaterGuruConnectionError(f"{target} timed out") from err

    # -- authentication -----------------------------------------------------

    async def async_login(self) -> None:
        """Full SRP login against the Cognito user pool."""
        from pycognito.aws_srp import AWSSRP  # noqa: PLC0415 - optional at import time

        loop = asyncio.get_running_loop()
        srp = AWSSRP(
            username=self._email,
            password=self._password,
            pool_id=USER_POOL_ID,
            client_id=CLIENT_ID,
            client=_UNUSED_BOTO_CLIENT,
        )

        auth_params = await loop.run_in_executor(None, srp.get_auth_params)
        challenge = await self._idp_call(
            "AWSCognitoIdentityProviderService.InitiateAuth",
            {
                "AuthFlow": "USER_SRP_AUTH",
                "ClientId": CLIENT_ID,
                "AuthParameters": auth_params,
            },
        )
        if challenge.get("ChallengeName") != "PASSWORD_VERIFIER":
            raise WaterGuruAuthError(
                f"Unexpected auth challenge: {challenge.get('ChallengeName')}"
            )

        responses = await loop.run_in_executor(
            None, srp.process_challenge, challenge["ChallengeParameters"], auth_params
        )
        result = await self._idp_call(
            "AWSCognitoIdentityProviderService.RespondToAuthChallenge",
            {
                "ChallengeName": "PASSWORD_VERIFIER",
                "ClientId": CLIENT_ID,
                "ChallengeResponses": responses,
            },
        )
        self._store_tokens(result)

    def _store_tokens(self, result: dict[str, Any]) -> None:
        auth = result.get("AuthenticationResult")
        if not auth or "IdToken" not in auth:
            raise WaterGuruAuthError("No tokens returned by Cognito")
        self._id_token = auth["IdToken"]
        # a refresh response does not repeat the refresh token
        self._refresh_token = auth.get("RefreshToken", self._refresh_token)
        self._token_expires = _utcnow() + dt.timedelta(
            seconds=int(auth.get("ExpiresIn", 3600))
        )
        claims = _decode_jwt_claims(self._id_token)
        self._user_id = claims.get("cognito:username") or claims.get("sub")
        # new tokens invalidate the derived AWS credentials
        self._credentials = None
        self._credentials_expire = None

    async def _async_refresh_tokens(self) -> None:
        """Use the refresh token; fall back to a full login."""
        if not self._refresh_token:
            await self.async_login()
            return
        try:
            result = await self._idp_call(
                "AWSCognitoIdentityProviderService.InitiateAuth",
                {
                    "AuthFlow": "REFRESH_TOKEN_AUTH",
                    "ClientId": CLIENT_ID,
                    "AuthParameters": {"REFRESH_TOKEN": self._refresh_token},
                },
            )
            self._store_tokens(result)
            _LOGGER.debug("WaterGuru tokens refreshed")
        except WaterGuruAuthError:
            _LOGGER.debug("Refresh token rejected, logging in again")
            await self.async_login()

    async def _async_ensure_credentials(self) -> dict[str, Any]:
        """Return valid temporary AWS credentials, refreshing as needed."""
        now = _utcnow()
        if (
            self._credentials
            and self._credentials_expire
            and now < self._credentials_expire - TOKEN_MARGIN
        ):
            return self._credentials

        if not self._id_token:
            await self.async_login()
        elif self._token_expires and now >= self._token_expires - TOKEN_MARGIN:
            await self._async_refresh_tokens()

        logins = {IDP_KEY: self._id_token}
        if not self._identity_id:
            identity = await self._identity_call(
                "AWSCognitoIdentityService.GetId",
                {"IdentityPoolId": IDENTITY_POOL_ID, "Logins": logins},
            )
            self._identity_id = identity["IdentityId"]

        creds = await self._identity_call(
            "AWSCognitoIdentityService.GetCredentialsForIdentity",
            {"IdentityId": self._identity_id, "Logins": logins},
        )
        credentials = creds["Credentials"]
        self._credentials = credentials
        expiration = credentials.get("Expiration")
        self._credentials_expire = (
            dt.datetime.fromtimestamp(expiration, tz=dt.timezone.utc)
            if isinstance(expiration, (int, float))
            else _utcnow() + dt.timedelta(minutes=55)
        )
        return credentials

    # -- data ---------------------------------------------------------------

    async def async_get_dashboard(self) -> dict[str, Any]:
        """Fetch the dashboard view (all water bodies and pods)."""
        async with self._lock:
            try:
                return await self._async_invoke_dashboard()
            except WaterGuruAuthError:
                # credentials may have gone stale mid-flight; retry once clean
                _LOGGER.debug("Dashboard call rejected, re-authenticating")
                self._credentials = None
                self._identity_id = None
                await self.async_login()
                return await self._async_invoke_dashboard()

    async def _async_invoke_dashboard(self) -> dict[str, Any]:
        credentials = await self._async_ensure_credentials()
        body = json.dumps(
            {
                "userId": self._user_id,
                "clientType": CLIENT_TYPE,
                "clientVersion": CLIENT_VERSION,
            }
        ).encode()

        headers = _sigv4_headers(
            access_key=credentials["AccessKeyId"],
            secret_key=credentials["SecretKey"],
            session_token=credentials["SessionToken"],
            host=LAMBDA_HOST,
            path=LAMBDA_PATH,
            body=body,
        )
        headers["User-Agent"] = "aws-sdk-iOS/2.24.3 iOS/14.7.1 en_US invoker"

        try:
            async with self._session.post(
                f"https://{LAMBDA_HOST}{LAMBDA_PATH}",
                headers=headers,
                data=body,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                text = await resp.text()
                if resp.status in (401, 403):
                    raise WaterGuruAuthError(f"Lambda rejected credentials: {text[:200]}")
                if resp.status != 200:
                    raise WaterGuruConnectionError(
                        f"Dashboard request failed ({resp.status}): {text[:200]}"
                    )
                if resp.headers.get("X-Amz-Function-Error"):
                    raise WaterGuruConnectionError(f"Lambda error: {text[:200]}")
                try:
                    return json.loads(text)
                except ValueError as err:
                    raise WaterGuruConnectionError(
                        f"Unparsable dashboard response: {err}"
                    ) from err
        except aiohttp.ClientError as err:
            raise WaterGuruConnectionError(f"Dashboard request failed: {err}") from err
        except asyncio.TimeoutError as err:
            raise WaterGuruConnectionError("Dashboard request timed out") from err

    async def async_validate(self) -> str:
        """Log in and return the account's user id (used by the config flow)."""
        await self.async_login()
        return self._user_id or self._email


class _UnusedBotoClient:
    """AWSSRP wants a boto3 client; we only use its crypto helpers."""

    def __getattr__(self, name: str) -> Any:  # pragma: no cover - never called
        raise RuntimeError(
            "WaterGuruClient performs its own HTTP calls; "
            f"pycognito tried to use the boto3 client ({name})"
        )


_UNUSED_BOTO_CLIENT = _UnusedBotoClient()
