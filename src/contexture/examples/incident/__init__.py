"""A deterministic Kubernetes incident-response server.

The scenario is fixed on purpose. Pointing the first demo at a real cluster
would mix two questions that need separate answers: is the framework correct,
and are the credentials, network, and RBAC correct? Everything here is served
from `fixtures`, so a failed run means the framework failed.
"""

from .role import DeploymentOps, IncidentResponse, KubernetesPlatform

__all__ = ["DeploymentOps", "IncidentResponse", "KubernetesPlatform"]
