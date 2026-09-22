"""Tests for revision list collection during promotion."""

import json
from unittest import mock

from sunbeam_release.promote import (
    charm_stable_revision,
    dependent_track,
    release_command,
    snap_promote_command,
    snap_stable_revision,
)


def _charm_status(track, source_rev, target_rev, source_status="active"):
    releases = [
        {
            "channel": f"{track}/candidate",
            "revision": source_rev,
            "status": source_status,
            "resources": [],
        },
        {
            "channel": f"{track}/stable",
            "revision": target_rev,
            "status": "active",
            "resources": [],
        },
    ]
    return [
        {
            "track": track,
            "mappings": [
                {
                    "base": {"channel": "24.04", "architecture": "amd64"},
                    "releases": releases,
                }
            ],
        }
    ]


def _run_mock(stdout):
    return mock.Mock(returncode=0, stdout=stdout)


def test_release_command_promotes_and_records_revisions():
    status = _charm_status("2023.1", source_rev=42, target_rev=40)
    with mock.patch(
        "sunbeam_release.promote.subprocess.run",
        return_value=_run_mock(json.dumps(status)),
    ):
        cmd, revisions = release_command(
            "keystone-k8s",
            track="2023.1",
            source_channel="candidate",
            target_channel="stable",
        )
    assert cmd is not None
    assert cmd == [
        "charmcraft",
        "release",
        "keystone-k8s",
        "--channel",
        "2023.1/stable",
        "--revision",
        "42",
    ]
    assert revisions["app"] == "keystone-k8s"
    assert revisions["type"] == "charm"
    assert revisions["source_revision"] == 42
    assert revisions["target_revision"] == 40
    assert revisions["promoted"] is True


def test_release_command_records_revisions_when_not_promoted():
    status = _charm_status("2023.1", source_rev=42, target_rev=42)
    with mock.patch(
        "sunbeam_release.promote.subprocess.run",
        return_value=_run_mock(json.dumps(status)),
    ):
        cmd, revisions = release_command(
            "keystone-k8s",
            track="2023.1",
            source_channel="candidate",
            target_channel="stable",
        )
    assert cmd is None
    assert revisions["source_revision"] == 42
    assert revisions["target_revision"] == 42
    assert revisions["promoted"] is False


def test_release_command_not_promoted_when_source_tracking():
    status = _charm_status(
        "2023.1", source_rev=42, target_rev=40, source_status="tracking"
    )
    with mock.patch(
        "sunbeam_release.promote.subprocess.run",
        return_value=_run_mock(json.dumps(status)),
    ):
        cmd, revisions = release_command(
            "keystone-k8s",
            track="2023.1",
            source_channel="candidate",
            target_channel="stable",
        )
    assert cmd is None
    assert revisions["source_revision"] == 42
    assert revisions["target_revision"] == 40
    assert revisions["promoted"] is False


def test_snap_promote_command_records_revisions():
    snap_info = (
        "snap-id: abc\n"
        "channels:\n"
        "  2023.1/candidate:  1.0 2024-01-01 (100) 10MB -\n"
        "  2023.1/stable:      1.0 2024-01-01 (99) 10MB -\n"
    )
    with mock.patch(
        "sunbeam_release.promote.subprocess.run",
        return_value=_run_mock(snap_info),
    ):
        cmd, revisions = snap_promote_command(
            "openstack",
            track="2023.1",
            source_channel="candidate",
            target_channel="stable",
        )
    assert cmd == [
        "snapcraft",
        "promote",
        "openstack",
        "--from-channel",
        "2023.1/candidate",
        "--to-channel",
        "2023.1/stable",
        "--yes",
    ]
    assert revisions["type"] == "snap"
    assert revisions["source_revision"] == "100"
    assert revisions["target_revision"] == "99"
    assert revisions["promoted"] is True


def _juju_info(channels):
    lines = ["name: fake", "channels: |"]
    lines.extend(f"  {c}" for c in channels)
    return "\n".join(lines)


def test_charm_stable_revision():
    juju_info = _juju_info(
        [
            "8.0/stable:     423  2026-07-01  (423)  26MB  amd64  ubuntu@22.04",
            "8.0/candidate:  444  2026-08-27  (444)  26MB  amd64  ubuntu@22.04",
        ]
    )
    with mock.patch(
        "sunbeam_release.promote.subprocess.run",
        return_value=_run_mock(juju_info),
    ):
        assert charm_stable_revision("mysql-k8s", "8.0") == 423


def test_charm_stable_revision_track_not_found():
    juju_info = _juju_info(
        ["8.0/stable:     423  2026-07-01  (423)  26MB  amd64  ubuntu@22.04"]
    )
    with mock.patch(
        "sunbeam_release.promote.subprocess.run",
        return_value=_run_mock(juju_info),
    ):
        assert charm_stable_revision("mysql-k8s", "8.4") is None


def test_charm_stable_revision_empty_channel():
    juju_info = _juju_info(["8.4/stable:     --"])
    with mock.patch(
        "sunbeam_release.promote.subprocess.run",
        return_value=_run_mock(juju_info),
    ):
        assert charm_stable_revision("mysql-k8s", "8.4") is None


def test_snap_stable_revision():
    snap_info = (
        "snap-id: abc\n"
        "channels:\n"
        "  2023.1/stable:      1.0 2024-01-01 (99) 10MB -\n"
    )
    with mock.patch(
        "sunbeam_release.promote.subprocess.run",
        return_value=_run_mock(snap_info),
    ):
        assert snap_stable_revision("openstack", "2023.1") == "99"


def test_revision_entries_promoted_and_not():
    from sunbeam_release.promote import revision_entries

    entries = revision_entries(
        [
            {
                "app": "a",
                "type": "charm",
                "source_revision": 42,
                "target_revision": 40,
                "promoted": True,
            },
            {
                "app": "b",
                "type": "charm",
                "source_revision": 42,
                "target_revision": 42,
                "promoted": False,
            },
        ]
    )
    assert entries[0] == {
        "app": "a",
        "current_revision": 40,
        "promoted_revision": 42,
    }
    assert entries[1] == {
        "app": "b",
        "current_revision": 42,
        "promoted_revision": 42,
    }


def test_dependent_track_per_release():
    assert dependent_track("microovn", "gazpacho") == "26.03"
    assert dependent_track("microovn", "caracal") == "24.03"
    assert dependent_track("microceph", "caracal") == "squid"
    assert dependent_track("microceph", "gazpacho") == "tentacle"
    assert dependent_track("microceph", "antelope") is None
    assert dependent_track("mysql-k8s", "caracal") == "8.0"


def test_dependent_track_k8s():
    assert dependent_track("k8s", "caracal") == "1.32-classic"
    assert dependent_track("k8s", "gazpacho") == "1.36-classic"
    assert dependent_track("k8s", "antelope") is None


def test_snap_promote_command_empty_source_returns_tuple():
    snap_info = (
        "snap-id: abc\n"
        "channels:\n"
        "  2023.1/stable:      1.0 2024-01-01 (99) 10MB -\n"
    )
    with mock.patch(
        "sunbeam_release.promote.subprocess.run",
        return_value=_run_mock(snap_info),
    ):
        cmd, revisions = snap_promote_command(
            "openstack",
            track="2023.1",
            source_channel="candidate",
            target_channel="stable",
        )
    assert cmd is None
    assert revisions["source_revision"] is None
    assert revisions["target_revision"] == "99"
    assert revisions["promoted"] is False


def test_charm_stable_revision_tracking_follows_above():
    juju_info = _juju_info(
        [
            "8.0/candidate:  444  2026-08-27  (444)  26MB  amd64  ubuntu@22.04",
            "8.0/stable:     ^",
        ]
    )
    with mock.patch(
        "sunbeam_release.promote.subprocess.run",
        return_value=_run_mock(juju_info),
    ):
        assert charm_stable_revision("mysql-k8s", "8.0") == 444


def test_charm_stable_revision_double_tracking_after():
    # trailing ^ lines must not clobber or shadow the stable revision
    juju_info = _juju_info(
        [
            "latest/stable:     299  2026-02-02  (299)  11MB  amd64  ubuntu@22.04",
            "latest/candidate:  ^",
            "latest/beta:       ^",
        ]
    )
    with mock.patch(
        "sunbeam_release.promote.subprocess.run",
        return_value=_run_mock(juju_info),
    ):
        assert charm_stable_revision("kratos", "latest") == 299


def test_charm_stable_revision_double_tracking_chain():
    # a chain of ^ lines resolves to the last real revision above
    juju_info = _juju_info(
        [
            "latest/edge:       447  2026-08-27  (447)  19MB  amd64  ubuntu@22.04",
            "v2/stable:         ^",
            "v2/candidate:      ^",
        ]
    )
    with mock.patch(
        "sunbeam_release.promote.subprocess.run",
        return_value=_run_mock(juju_info),
    ):
        assert charm_stable_revision("fake", "v2") == 447


def test_render_yaml_and_table():
    from sunbeam_release.promote import render_table, render_yaml

    sections = [
        (
            "charms:",
            [
                {
                    "app": "a",
                    "current_revision": 1,
                    "promoted_revision": 2,
                }
            ],
        ),
        ("empty:", []),
        (
            "dependent_charms:",
            [
                {
                    "app": "m",
                    "channel": "1/stable",
                    "stable_revision": None,
                }
            ],
        ),
    ]
    yaml_out = render_yaml(sections)
    assert "charms:" in yaml_out
    assert "- app: a" in yaml_out
    assert "promoted_revision: 2" in yaml_out
    assert "stable_revision: null" in yaml_out
    assert "empty:" not in yaml_out
    table_out = render_table(sections)
    assert "dependent_charms:" in table_out
    assert "1/stable           -" in table_out
    assert "empty:" not in table_out


def test_charm_metadata_uses_exported_credential():
    import os

    from sunbeam_release.promote import charm_metadata

    with (
        mock.patch.dict(os.environ, {"CHARMHUB_AUTH": "exported-cred"}),
        mock.patch(
            "sunbeam_release.promote.subprocess.run",
            return_value=_run_mock("[]"),
        ) as run,
    ):
        charm_metadata("keystone-k8s")
        assert (
            run.call_args.kwargs["env"]["CHARMCRAFT_AUTH"] == "exported-cred"
        )
