"""IPv8 payload definitions for Lab 1 protocol."""

from ipv8.messaging.lazy_payload import VariablePayload, vp_compile


@vp_compile
class SubmissionPayload(VariablePayload):
    msg_id = 1
    format_list = ["varlenHutf8", "varlenHutf8", "q"]
    names = ["email", "github_url", "nonce"]


@vp_compile
class SubmissionResponsePayload(VariablePayload):
    msg_id = 2
    format_list = ["?", "varlenHutf8"]
    names = ["success", "message"]
