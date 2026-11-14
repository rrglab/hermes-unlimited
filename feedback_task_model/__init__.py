"""Optional standalone Hermes Community Feedback plugin.

May coexist with an older Hermes Unlimited installation. Do not enable this
sidecar alongside an Unlimited plugin registering the same feedback hooks.
"""


def register(ctx):
    from .hermes_hooks import register_feedback_hooks
    register_feedback_hooks(ctx)
