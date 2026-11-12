"""Tests for LIF-1402: maintainer feedback import + human DCO checkpoint.

SPDX-License-Identifier: GPL-2.0-only
"""
import ast
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import upstreamreview as ur  # noqa: E402

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "lif1402" / "feedback.json").read_text())

HUMAN = ur.Reviewer("human-submitter", "Human Submitter", "human@example.org", "human")
AGENT = ur.Reviewer("yrsa-agent", "Yrsa Agent", "agent@example.org", "agent")
BOT = ur.Reviewer("ci-bot", "CI Bot", "bot@example.org", "bot")


def board_with_checkpoint():
    board = ur.UpstreamReviewBoard()
    ckpt = board.register_checkpoint(
        FIXTURE["dossier_id"], FIXTURE["dossier_digest"],
        FIXTURE["patch_text"], FIXTURE["created_at"])
    return board, ckpt


def board_with_feedback():
    board, ckpt = board_with_checkpoint()
    for wire in FIXTURE["feedback"]:
        board.import_feedback(wire)
    return board, ckpt


def fresh_patch_board(patch_text, created_at="2026-11-10T08:00:00Z"):
    board = ur.UpstreamReviewBoard()
    digest = ur.patch_digest(patch_text)
    ckpt = board.register_checkpoint("dossier-x", digest, patch_text, created_at)
    return board, ckpt


# -- feedback import ---------------------------------------------------

def test_fixture_patch_digest_matches_pin():
    assert ur.patch_digest(FIXTURE["patch_text"]) == FIXTURE["dossier_digest"]


def test_fixture_feedback_imports_and_summary():
    board, ckpt = board_with_feedback()
    records = board.feedback_for(FIXTURE["dossier_digest"])
    assert len(records) == 4
    summary = board.feedback_summary(FIXTURE["dossier_digest"])
    assert summary["reviewed-by"] == 1
    assert summary["acked-by"] == 1
    assert summary["tested-by"] == 1
    assert summary["requested-changes"] == 1
    assert summary["nack"] == 0


def test_make_feedback_round_trips():
    wire = ur.make_feedback("dossier-x", FIXTURE["dossier_digest"], "Marta Maintainer",
                            "marta@example.org", "comment", "b4", "A note.",
                            "2026-11-10T10:00:00Z")
    record = ur.feedback_from_dict(wire)
    assert record.kind == "comment"
    assert record.feedback_id.startswith("fb-")


def test_feedback_missing_key_refused():
    wire = dict(FIXTURE["feedback"][0])
    del wire["body"]
    with pytest.raises(ur.MalformedFeedbackError):
        ur.feedback_from_dict(wire)


def test_feedback_extra_key_refused():
    wire = dict(FIXTURE["feedback"][0])
    wire["surprise"] = "x"
    with pytest.raises(ur.MalformedFeedbackError):
        ur.feedback_from_dict(wire)


def test_feedback_wrong_schema_refused():
    wire = dict(FIXTURE["feedback"][0])
    wire["schema"] = "lifthrasir.something-else.v9"
    with pytest.raises(ur.MalformedFeedbackError):
        ur.feedback_from_dict(wire)


def test_feedback_bad_kind_refused():
    wire = ur.make_feedback("dossier-x", FIXTURE["dossier_digest"], "A B",
                            "a@example.org", "comment", "email", "hi",
                            "2026-11-10T10:00:00Z")
    wire["kind"] = "lgtm-plus-plus"
    wire["content_digest"] = ur.content_digest_for(
        {k: wire[k] for k in wire if k != "content_digest"})
    with pytest.raises(ur.MalformedFeedbackError):
        ur.feedback_from_dict(wire)


def test_feedback_bad_source_refused():
    wire = dict(FIXTURE["feedback"][0])
    wire["source"] = "telepathy"
    with pytest.raises(ur.MalformedFeedbackError):
        ur.feedback_from_dict(wire)


def test_feedback_bad_email_refused():
    wire = dict(FIXTURE["feedback"][0])
    wire["maintainer_email"] = "not-an-email"
    with pytest.raises(ur.MalformedFeedbackError):
        ur.feedback_from_dict(wire)


def test_feedback_bad_timestamp_refused():
    wire = dict(FIXTURE["feedback"][0])
    wire["received_at"] = "last Tuesday-ish"
    with pytest.raises(ur.MalformedFeedbackError):
        ur.feedback_from_dict(wire)


def test_feedback_tampered_body_refused_by_digest():
    wire = dict(FIXTURE["feedback"][0])
    wire["body"] = wire["body"] + " (edited in transit)"
    with pytest.raises(ur.FeedbackDigestError):
        ur.feedback_from_dict(wire)


def test_feedback_malformed_digest_pin_refused():
    wire = dict(FIXTURE["feedback"][0])
    wire["content_digest"] = "sha256:not-hex"
    with pytest.raises(ur.MalformedFeedbackError):
        ur.feedback_from_dict(wire)


def test_feedback_signoff_body_refused_as_dco_channel():
    wire = dict(FIXTURE["feedback"][0])
    wire["body"] = "Looks fine.\nSigned-off-by: Marta Maintainer <marta@example.org>"
    with pytest.raises(ur.FeedbackDCOError):
        ur.feedback_from_dict(wire)


def test_feedback_lowercase_signoff_also_refused():
    wire = dict(FIXTURE["feedback"][0])
    wire["body"] = "ok\nsigned-off-by: x <x@example.org>"
    with pytest.raises(ur.FeedbackDCOError):
        ur.feedback_from_dict(wire)


def test_import_feedback_for_unknown_digest_refused():
    board = ur.UpstreamReviewBoard()
    with pytest.raises(ur.UnknownCheckpointError):
        board.import_feedback(FIXTURE["feedback"][0])


def test_import_feedback_is_idempotent():
    board, ckpt = board_with_checkpoint()
    first = board.import_feedback(FIXTURE["feedback"][0])
    second = board.import_feedback(FIXTURE["feedback"][0])
    assert first.feedback_id == second.feedback_id
    assert len(board.feedback_for(FIXTURE["dossier_digest"])) == 1


def test_feedback_never_decides_a_checkpoint():
    board, ckpt = board_with_feedback()
    wire = ur.make_feedback(FIXTURE["dossier_id"], FIXTURE["dossier_digest"],
                            "Nadia Nack", "nadia@example.org", "nack", "email",
                            "This approach is wrong; do not submit.",
                            "2026-11-10T14:00:00Z")
    board.import_feedback(wire)
    assert board.get_checkpoint(ckpt.checkpoint_id).state == "awaiting-human"
    with pytest.raises(ur.CheckpointStateError):
        board.submission_package(ckpt.checkpoint_id)


def test_feedback_quota_refused():
    board, ckpt = board_with_checkpoint()
    for i in range(ur.MAX_FEEDBACK_PER_DOSSIER):
        board.import_feedback(ur.make_feedback(
            FIXTURE["dossier_id"], FIXTURE["dossier_digest"], "Marta Maintainer",
            "marta@example.org", "comment", "email", f"note {i}",
            "2026-11-10T10:00:00Z"))
    with pytest.raises(ur.FeedbackQuotaError):
        board.import_feedback(ur.make_feedback(
            FIXTURE["dossier_id"], FIXTURE["dossier_digest"], "Marta Maintainer",
            "marta@example.org", "comment", "email", "one too many",
            "2026-11-10T10:01:00Z"))


# -- checkpoint registration --------------------------------------------

def test_register_checkpoint_digest_mismatch_refused():
    board = ur.UpstreamReviewBoard()
    wrong = "sha256:" + "0" * 64
    with pytest.raises(ur.DossierMismatchError):
        board.register_checkpoint("dossier-x", wrong, "some patch", "2026-11-10T08:00:00Z")


def test_register_checkpoint_duplicate_refused():
    board, ckpt = board_with_checkpoint()
    with pytest.raises(ur.DuplicateCheckpointError):
        board.register_checkpoint(FIXTURE["dossier_id"], FIXTURE["dossier_digest"],
                                  FIXTURE["patch_text"], FIXTURE["created_at"])


def test_register_checkpoint_bad_id_refused():
    board = ur.UpstreamReviewBoard()
    digest = ur.patch_digest("patch")
    with pytest.raises(ur.MalformedCheckpointError):
        board.register_checkpoint("Bad ID!", digest, "patch", "2026-11-10T08:00:00Z")


def test_get_unknown_checkpoint_refused():
    board = ur.UpstreamReviewBoard()
    with pytest.raises(ur.UnknownCheckpointError):
        board.get_checkpoint("ckpt-nope")


def test_reviewer_bad_email_refused():
    with pytest.raises(ur.MalformedCheckpointError):
        ur.Reviewer("ok-id", "Name", "nope", "human")


def test_reviewer_bad_id_refused():
    with pytest.raises(ur.MalformedCheckpointError):
        ur.Reviewer("Bad ID", "Name", "a@example.org", "human")


# -- the human decision ---------------------------------------------------

def test_agent_reviewer_cannot_approve():
    board, ckpt = board_with_feedback()
    with pytest.raises(ur.AgentReviewerError):
        board.record_decision(ckpt.checkpoint_id, AGENT, "approved-for-submission",
                              "2026-11-11T09:00:00Z", dco_reviewed=True,
                              feedback_reviewed=True)
    assert board.get_checkpoint(ckpt.checkpoint_id).state == "awaiting-human"


def test_agent_reviewer_cannot_reject_either():
    board, ckpt = board_with_checkpoint()
    with pytest.raises(ur.AgentReviewerError):
        board.record_decision(ckpt.checkpoint_id, AGENT, "rejected", "2026-11-11T09:00:00Z")


def test_bot_reviewer_refused():
    board, ckpt = board_with_checkpoint()
    with pytest.raises(ur.AgentReviewerError):
        board.record_decision(ckpt.checkpoint_id, BOT, "changes-requested",
                              "2026-11-11T09:00:00Z")


def test_approval_requires_dco_attestation():
    board, ckpt = board_with_checkpoint()
    with pytest.raises(ur.DCOAttestationError):
        board.record_decision(ckpt.checkpoint_id, HUMAN, "approved-for-submission",
                              "2026-11-11T09:00:00Z", dco_reviewed=False)


def test_approval_requires_feedback_review_when_feedback_stands():
    board, ckpt = board_with_feedback()
    with pytest.raises(ur.FeedbackReviewRequiredError):
        board.record_decision(ckpt.checkpoint_id, HUMAN, "approved-for-submission",
                              "2026-11-11T09:00:00Z", dco_reviewed=True,
                              feedback_reviewed=False)


def test_approval_without_any_feedback_needs_no_feedback_attestation():
    board, ckpt = board_with_checkpoint()
    decided = board.record_decision(ckpt.checkpoint_id, HUMAN, "approved-for-submission",
                                    "2026-11-11T09:00:00Z", dco_reviewed=True)
    assert decided.state == "approved-for-submission"


def test_approval_success_and_submission_package():
    board, ckpt = board_with_feedback()
    board.record_decision(ckpt.checkpoint_id, HUMAN, "approved-for-submission",
                          "2026-11-11T09:00:00Z", dco_reviewed=True,
                          feedback_reviewed=True, note="Split done in the resubmission.")
    package = board.submission_package(ckpt.checkpoint_id)
    assert package["sent"] is False
    assert package["signoff_added_by_system"] is False
    assert package["submission_channel"] == "human-outside-system"
    assert package["decision"]["reviewer"]["email"] == "human@example.org"
    assert package["feedback_summary"]["requested-changes"] == 1
    assert "Signed-off-by" not in json.dumps(package)


def test_decision_is_final():
    board, ckpt = board_with_checkpoint()
    board.record_decision(ckpt.checkpoint_id, HUMAN, "approved-for-submission",
                          "2026-11-11T09:00:00Z", dco_reviewed=True)
    with pytest.raises(ur.CheckpointStateError):
        board.record_decision(ckpt.checkpoint_id, HUMAN, "rejected", "2026-11-11T10:00:00Z")


def test_changes_requested_is_terminal_and_yields_no_package():
    board, ckpt = board_with_feedback()
    board.record_decision(ckpt.checkpoint_id, HUMAN, "changes-requested",
                          "2026-11-11T09:00:00Z", note="Split the change first.")
    with pytest.raises(ur.CheckpointStateError):
        board.submission_package(ckpt.checkpoint_id)


def test_rejection_is_terminal():
    board, ckpt = board_with_checkpoint()
    decided = board.record_decision(ckpt.checkpoint_id, HUMAN, "rejected",
                                    "2026-11-11T09:00:00Z")
    assert decided.state == "rejected"
    with pytest.raises(ur.CheckpointStateError):
        board.record_decision(ckpt.checkpoint_id, HUMAN, "approved-for-submission",
                              "2026-11-11T10:00:00Z", dco_reviewed=True)


def test_bad_decision_value_refused():
    board, ckpt = board_with_checkpoint()
    with pytest.raises(ur.MalformedCheckpointError):
        board.record_decision(ckpt.checkpoint_id, HUMAN, "ship-it", "2026-11-11T09:00:00Z")


def test_decision_before_creation_refused():
    board, ckpt = board_with_checkpoint()
    with pytest.raises(ur.MalformedCheckpointError):
        board.record_decision(ckpt.checkpoint_id, HUMAN, "rejected", "2026-11-09T09:00:00Z")


def test_stale_patch_approval_refused():
    board, ckpt = board_with_checkpoint()
    revised = FIXTURE["patch_text"] + "\nOne more line sneaked in.\n"
    with pytest.raises(ur.StaleCheckpointError):
        board.record_decision(ckpt.checkpoint_id, HUMAN, "approved-for-submission",
                              "2026-11-11T09:00:00Z", dco_reviewed=True,
                              current_patch_text=revised)


# -- the sign-off scan ------------------------------------------------------

def test_signoff_by_agent_in_patch_refused():
    patch = "Subject: [PATCH] x\n\nSigned-off-by: Yrsa Agent <agent@example.org>\n"
    board, ckpt = fresh_patch_board(patch)
    with pytest.raises(ur.SignoffViolationError):
        board.record_decision(ckpt.checkpoint_id, HUMAN, "approved-for-submission",
                              "2026-11-11T09:00:00Z", dco_reviewed=True)
    assert board.get_checkpoint(ckpt.checkpoint_id).state == "awaiting-human"


def test_signoff_by_third_party_refused():
    patch = "Subject: [PATCH] x\n\nSigned-off-by: Someone Else <else@example.org>\n"
    board, ckpt = fresh_patch_board(patch)
    with pytest.raises(ur.SignoffViolationError):
        board.record_decision(ckpt.checkpoint_id, HUMAN, "approved-for-submission",
                              "2026-11-11T09:00:00Z", dco_reviewed=True)


def test_unparseable_signoff_refused():
    patch = "Subject: [PATCH] x\n\nSigned-off-by: anonymous coward\n"
    board, ckpt = fresh_patch_board(patch)
    with pytest.raises(ur.SignoffViolationError):
        board.record_decision(ckpt.checkpoint_id, HUMAN, "approved-for-submission",
                              "2026-11-11T09:00:00Z", dco_reviewed=True)


def test_signoff_by_deciding_human_accepted():
    patch = ("From: Human Submitter <human@example.org>\nSubject: [PATCH] x\n\n"
             "Signed-off-by: Human Submitter <human@example.org>\n")
    board, ckpt = fresh_patch_board(patch)
    decided = board.record_decision(ckpt.checkpoint_id, HUMAN, "approved-for-submission",
                                    "2026-11-11T09:00:00Z", dco_reviewed=True)
    assert decided.state == "approved-for-submission"


def test_find_signoffs_is_case_insensitive():
    text = "a\nsigned-off-by: X <x@example.org>\nSIGNED-OFF-BY: Y <y@example.org>\n"
    assert len(ur.find_signoffs(text)) == 2


# -- records, surfaces, exports ----------------------------------------------

def test_upstream_review_record_contents():
    board, ckpt = board_with_feedback()
    record = ur.upstream_review_record(board, ckpt.checkpoint_id)
    assert record["checkpoint"]["state"] == "awaiting-human"
    assert len(record["feedback"]) == 4
    assert record["evidence_status"] == "lab-verified"
    assert any("in-memory" in limit for limit in record["limitations"])


def test_module_has_no_send_or_system_surface():
    source = Path(ur.__file__).read_text()
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"socket", "smtplib", "subprocess", "urllib", "os", "sys",
                 "requests", "http", "ftplib", "pathlib"}
    assert not (imported & forbidden), f"forbidden imports: {imported & forbidden}"
    assert "sendmail" not in source
    assert "send_email" not in source


DESIRED_EXPORTS = [
    "UPSTREAM_REVIEW_SCHEMA", "UPSTREAM_REVIEW_SCHEMA_VERSION", "EVIDENCE_STATUS",
    "TIMESTAMP_FORMAT", "FEEDBACK_KINDS", "FEEDBACK_SOURCES", "HUMAN_KIND",
    "DECISION_APPROVED", "DECISION_CHANGES", "DECISION_REJECTED", "DECISIONS",
    "STATE_AWAITING", "CHECKPOINT_STATES", "SUBMISSION_CHANNEL",
    "MAX_FEEDBACK_BODY_CHARS", "MAX_PATCH_CHARS", "MAX_FEEDBACK_PER_DOSSIER",
    "MAX_NOTE_CHARS", "UpstreamReviewError", "MalformedFeedbackError",
    "FeedbackDigestError", "FeedbackDCOError", "FeedbackQuotaError",
    "MalformedCheckpointError", "DossierMismatchError", "DuplicateCheckpointError",
    "UnknownCheckpointError", "AgentReviewerError", "DCOAttestationError",
    "FeedbackReviewRequiredError", "StaleCheckpointError", "SignoffViolationError",
    "CheckpointStateError", "Reviewer", "FeedbackRecord", "feedback_from_dict",
    "make_feedback", "Decision", "ReviewCheckpoint", "UpstreamReviewBoard",
    "content_digest_for", "patch_digest", "find_signoffs", "upstream_review_record",
]


def test_desired_exports_all_exist_in_module():
    for name in DESIRED_EXPORTS:
        assert hasattr(ur, name), f"module is missing desired export {name}"
