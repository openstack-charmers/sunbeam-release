# Copyright 2021 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Release helpers for promotion of charms between channels."""

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import (
    Union,
    List,
    Tuple,
)

import click

OPENSTACK_CHARMS = [
    "aodh-k8s",
    "barbican-k8s",
    "ceilometer-k8s",
    "cinder-ceph-k8s",
    "cinder-k8s",
    "cinder-volume",
    "cinder-volume-ceph",
    "cinder-volume-hitachi",
    "cinder-volume-purestorage",
    "cinder-volume-hpe3par",
    "cinder-volume-infinidat",
    # "cloudkitty-k8s",
    "designate-k8s",
    "epa-orchestrator",
    "glance-k8s",
    "gnocchi-k8s",
    "heat-k8s",
    "horizon-k8s",
    "ironic-k8s",
    "ironic-conductor-k8s",
    "keystone-k8s",
    "keystone-ldap-k8s",
    "keystone-saml-k8s",
    "magnum-k8s",
    "manila-cephfs-k8s",
    "manila-data",
    "manila-k8s",
    "masakari-k8s",
    "neutron-k8s",
    "neutron-baremetal-switch-config-k8s",
    "neutron-generic-switch-config-k8s",
    "nova-k8s",
    "nova-ironic-k8s",
    "octavia-k8s",
    "openstack-exporter-k8s",
    "openstack-hypervisor",
    "openstack-images-sync-k8s",
    "openstack-network-agents",
    "openstack-port-cni-k8s",
    "sunbeam-ovn-proxy",
    "placement-k8s",
    "sunbeam-clusterd",
    "sunbeam-machine",
    "tempest-k8s",
    "watcher-k8s",
]

OVN_CHARMS = [
    "ovn-relay-k8s",
    "ovn-central-k8s",
]

CONSUL_CHARMS = [
    "consul-k8s",
    "consul-client",
]

OPENSTACK_SNAPS = [
    "openstack",
    "openstack-hypervisor",
    "cinder-volume",
    "openstack-network-agents",
    "manila-data",
    "epa-orchestrator",
]

CONSUL_SNAPS = [
    "consul-client",
]

# Charms from sunbeam dependent projects (sunbeam-terraform plan and
# snap-openstack manifests), not promoted by this tool - only their
# track/stable revision is reported.
# ponytail: static tracks taken from the current terraform plan, update
# per release if promoting older ones. Per-release tracks (microceph,
# k8s) live in TRACKS and are resolved via dependent_track; microovn
# follows the OVN track.
DEPENDENT_CHARMS = {
    "mysql-k8s": "8.0",
    "mysql-router-k8s": "8.0",
    "traefik-k8s": "latest",
    "vault-k8s": "1.18",
    "self-signed-certificates": "1",
    "manual-tls-certificates": "1",
    "opentelemetry-collector": "2",
    "opentelemetry-collector-k8s": "2",
    "kratos-external-idp-integrator": "0.2",
    "microceph": None,
    "microovn": None,
    "microcluster-token-distributor": "v1",
    "role-distributor": "latest",
    "multus": "latest",
    # observability feature: local COS stack and hardware observer
    # (the COS traefik instance deploys the same traefik-k8s charm)
    "alertmanager-k8s": "1",
    "grafana-k8s": "1",
    "catalogue-k8s": "1",
    "prometheus-k8s": "1",
    "loki-k8s": "1",
    "hardware-observer": "latest",
}

DEPENDENT_SNAPS = {
    "microceph": None,
    "microovn": None,
    "k8s": None,
}

WORKFLOWS = {
    "edge": "beta",
    "beta": "candidate",
    "candidate": "stable",
}

TRACKS = {
    "antelope": {
        "openstack": "2023.1",
        "ovn": "23.03",
        "rabbitmq-k8s": "3.12",
        "designate-bind-k8s": "9",
    },
    "bobcat": {
        "openstack": "2023.2",
        "ovn": "23.09",
        "rabbitmq-k8s": "3.12",
        "designate-bind-k8s": "9",
    },
    "caracal": {
        "openstack": "2024.1",
        "ovn": "24.03",
        "rabbitmq-k8s": "3.12",
        "designate-bind-k8s": "9",
        "consul": "1.19",
        "microceph": "squid",
        "k8s": "1.32-classic",
    },
    "epoxy": {
        "openstack": "2025.1",
        "ovn": "25.03",
        "rabbitmq-k8s": "3.12",
        "designate-bind-k8s": "9",
        "consul": "1.19",
        "microceph": "squid",
        "k8s": "1.32-classic",
    },
    "gazpacho": {
        "openstack": "2026.1",
        "ovn": "26.03",
        "rabbitmq-k8s": "4.0",
        "designate-bind-k8s": "9",
        "consul": "1.19",
        "microceph": "tentacle",
        "k8s": "1.36-classic",
    },
}


def charmcraft_env() -> dict:
    """Environment for charmcraft calls.

    When the CHARMHUB_AUTH env var is set (exported charmcraft
    credentials, e.g. in CI) it is passed to charmcraft as
    CHARMCRAFT_AUTH. Without it charmcraft falls back to the
    logged-in credentials.
    """
    env = os.environ.copy()
    auth = os.environ.get("CHARMHUB_AUTH")
    if auth:
        env["CHARMCRAFT_AUTH"] = auth
    return env


def charm_metadata(app: str) -> dict:
    """Retrieve metadata about a specific charm."""
    cmd = ["charmcraft", "status", app, "--format", "json"]
    process = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        env=charmcraft_env(),
    )
    return json.loads(process.stdout.strip())


def snap_metadata(snap: str) -> dict:
    """Retrieve metadata about a specific snap.

    Retries once - the snap store intermittently returns transient
    errors (e.g. 'no snap found') for existing snaps.
    """
    cmd = ["snap", "info", snap]
    for attempt in (0, 1):
        try:
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )
            break
        except subprocess.CalledProcessError:
            if attempt:
                raise
            print(f"  snap info {snap} failed, retrying...")
            time.sleep(2)
    output = process.stdout.strip()

    # Parse the channels section
    channels = {}
    in_channels_section = False

    for line in output.split("\n"):
        if line.startswith("channels:"):
            in_channels_section = True
            continue

        if in_channels_section:
            # Stop if we hit an empty line or a new section
            if not line.strip() or (line and not line.startswith(" ")):
                break

            # Parse channel line format: "  track/risk:  version date (revision) size -"
            parts = line.strip().split()
            if len(parts) >= 2:
                channel = parts[0].rstrip(":")
                if parts[1] == "--":
                    # Channel is empty
                    channels[channel] = None
                elif parts[1] == "^":
                    # Channel is tracking the channel above
                    channels[channel] = "tracking"
                else:
                    # Extract revision from parentheses
                    revision = None
                    for part in parts:
                        if part.startswith("(") and part.endswith(")"):
                            revision = part.strip("()")
                            break
                    channels[channel] = {
                        "version": parts[1],
                        "revision": revision,
                    }

    return {"channels": channels}


def release_command(
    app: str,
    track: str,
    source_channel: str,
    target_channel: str,
    base_channels: List[str] = ["22.04", "24.04"],
    base_archs: List[str] = ["amd64"],
) -> Tuple[Union[List[str], None], dict]:
    """Generate a charmcraft release command to promote between tracks."""
    release_cmd = None
    revisions = {
        "app": app,
        "type": "charm",
        "source_revision": None,
        "target_revision": None,
        "promoted": False,
    }
    charm_info = charm_metadata(app)
    print(
        f"Checking {app}: {track}/{source_channel}->{track}/{target_channel}"
    )
    for s in charm_info:
        if s["track"] == track:
            for mapping in s["mappings"]:
                if (
                    mapping["base"]["channel"] in base_channels
                    and mapping["base"]["architecture"] in base_archs
                ):
                    source_release = None
                    target_release = None
                    for release in mapping["releases"]:
                        if release["channel"] == f"{track}/{source_channel}":
                            source_release = release
                        if release["channel"] == f"{track}/{target_channel}":
                            target_release = release

                    if source_release:
                        revisions["source_revision"] = source_release.get(
                            "revision"
                        )
                    if target_release:
                        revisions["target_revision"] = target_release.get(
                            "revision"
                        )

                    if source_release and target_release:
                        if source_release["status"] == "tracking":
                            # Source channel is tracking the channel
                            # above, skip
                            print(
                                "Source track follows target track, skipping"
                            )
                            continue
                        if (
                            source_release["revision"]
                            == target_release["revision"]
                        ):
                            # Source == Target - so skip
                            print("Source and target revision match, skipping")
                            continue
                        release_cmd = [
                            "charmcraft",
                            "release",
                            app,
                            "--channel",
                            f"{track}/{target_channel}",
                            "--revision",
                            str(source_release["revision"]),
                        ]
                        for resource in source_release["resources"]:
                            release_cmd.append("--resource")
                            release_cmd.append(
                                f"{resource['name']}:{resource['revision']}"
                            )
                        revisions["promoted"] = True
                        break

    return release_cmd, revisions


def snap_promote_command(
    snap: str,
    track: str,
    source_channel: str,
    target_channel: str,
) -> Tuple[Union[List[str], None], dict]:
    """Generate a snapcraft promote command to promote between channels."""
    from_channel = f"{track}/{source_channel}"
    to_channel = f"{track}/{target_channel}"
    revisions = {
        "app": snap,
        "type": "snap",
        "source_revision": None,
        "target_revision": None,
        "promoted": False,
    }

    print(f"Checking snap {snap}: {from_channel}->{to_channel}")

    try:
        snap_info = snap_metadata(snap)
        channels = snap_info.get("channels", {})

        source_info = channels.get(from_channel)
        target_info = channels.get(to_channel)

        if isinstance(source_info, dict):
            revisions["source_revision"] = source_info.get("revision")
        if isinstance(target_info, dict):
            revisions["target_revision"] = target_info.get("revision")

        # Check if source channel exists and has content
        if source_info is None:
            print(f"  Source channel {from_channel} is empty, skipping")
            return None, revisions

        if source_info == "tracking":
            print(f"  Source channel {from_channel} is tracking, skipping")
            return None, revisions

        # Check if target channel exists
        if target_info is None:
            print(f"  Target channel {to_channel} is empty, will promote")
        elif target_info == "tracking":
            print(f"  Target channel {to_channel} is tracking, will promote")
        elif isinstance(source_info, dict) and isinstance(target_info, dict):
            # Compare revisions
            if source_info.get("revision") == target_info.get("revision"):
                print(
                    f"  Source and target revision match ({source_info.get('revision')}), skipping"
                )
                return None, revisions
            else:
                print(
                    f"  Source revision {source_info.get('revision')} != target revision {target_info.get('revision')}, will promote"
                )

        promote_cmd = [
            "snapcraft",
            "promote",
            snap,
            "--from-channel",
            from_channel,
            "--to-channel",
            to_channel,
            "--yes",
        ]

        revisions["promoted"] = True
        return promote_cmd, revisions

    except subprocess.CalledProcessError as e:
        print(f"  Error getting snap info: {e.stderr or e}")
        return None, revisions


def charm_stable_revision(app: str, track: str) -> Union[int, None]:
    """Retrieve the revision of a charm in track/stable via juju info.

    Used for dependent project charms where charmcraft status is not
    available (requires charm admin rights). Channel lines look like
    'channel:  <version>  <date>  (<revision>)  <size>  ...', where
    version may be non-numeric; the revision is in parentheses.
    """
    process = subprocess.run(
        ["juju", "info", app],
        capture_output=True,
        text=True,
        check=True,
    )
    channel = f"{track}/stable:"
    in_channels = False
    last_revision = None
    for line in process.stdout.splitlines():
        if line.startswith("channels:"):
            in_channels = True
            continue
        if not in_channels:
            continue
        if not line.startswith(" "):
            break
        parts = line.strip().split()
        if not parts:
            continue
        if parts[0] == channel:
            for part in parts:
                if part.startswith("(") and part.endswith(")"):
                    return int(part.strip("()"))
            # "^" tracks the channel above, "--" is empty
            if len(parts) > 1 and parts[1] == "^":
                return last_revision
            return None
        for part in parts:
            if part.startswith("(") and part.endswith(")"):
                last_revision = int(part.strip("()"))
    return None


def snap_stable_revision(snap: str, track: str) -> Union[str, None]:
    """Retrieve the revision of a snap in track/stable."""
    info = snap_metadata(snap).get("channels", {}).get(f"{track}/stable")
    if isinstance(info, dict):
        return info.get("revision")
    return None


def dependent_track(app: str, release: str) -> Union[str, None]:
    """Resolve the track for a dependent charm or snap.

    Apps with per-release tracks (microceph, k8s) are looked up in
    TRACKS; microovn follows the OVN track; the rest use the static
    track from DEPENDENT_CHARMS/DEPENDENT_SNAPS.
    """
    if app == "microovn":
        return TRACKS[release]["ovn"]
    if app in TRACKS[release]:
        return TRACKS[release][app]
    return DEPENDENT_CHARMS.get(app) or DEPENDENT_SNAPS.get(app)


def revision_entries(revs: List[dict]) -> List[dict]:
    """Convert revision dicts to output entries."""
    entries = []
    for rev in revs:
        current = rev["target_revision"]
        promoted = rev["source_revision"] if rev["promoted"] else current
        entries.append(
            {
                "app": rev["app"],
                "current_revision": current,
                "promoted_revision": promoted,
            }
        )
    return entries


def render_table(sections: List[Tuple[str, List[dict]]]) -> str:
    """Render revision sections as an aligned text table."""
    lines = []
    for label, entries in sections:
        if not entries:
            continue
        keys = [k for k in entries[0] if k != "app"]
        lines.append(label)
        lines.append(f"{'app':<40} " + " ".join(f"{k:<18}" for k in keys))
        for entry in entries:
            row = " ".join(
                f"{str(entry[k]) if entry[k] is not None else '-':<18}"
                for k in keys
            )
            lines.append(f"{entry['app']:<40} " + row.rstrip())
    return "\n".join(lines)


def render_yaml(sections: List[Tuple[str, List[dict]]]) -> str:
    """Render revision sections as yaml."""
    lines = []
    for label, entries in sections:
        if not entries:
            continue
        lines.append(label)
        for entry in entries:
            lines.append(f"- app: {entry['app']}")
            for key in entry:
                if key == "app":
                    continue
                value = entry[key] if entry[key] is not None else "null"
                lines.append(f"  {key}: {value}")
    return "\n".join(lines)


@click.command()
@click.option(
    "--source",
    default="candidate",
    help="Source channel for promotion",
    type=click.Choice(WORKFLOWS.keys()),
    show_default=True,
)
@click.option(
    "--release",
    default="antelope",
    help="Sunbeam release for tracks",
    type=click.Choice(TRACKS.keys()),
    show_default=True,
)
@click.option("--dry-run", "-d", default=False, is_flag=True)
@click.option(
    "--format",
    "output_format",
    default="both",
    help="Revision list output format",
    type=click.Choice(["table", "yaml", "both"]),
    show_default=True,
)
def promote(
    source: str,
    release: str,
    dry_run: bool,
    output_format: str,
) -> None:
    """Promote charms between channels."""
    if source not in WORKFLOWS.keys():
        raise click.BadOptionUsage(
            option_name="source",
            message=(
                f"source {source} not supported - must"
                f" be one of {','.join(WORKFLOWS.keys())}"
            ),
        )

    release_cmds = []
    revision_list = []

    for charm in OPENSTACK_CHARMS:
        cmd, revisions = release_command(
            charm,
            track=TRACKS[release]["openstack"],
            source_channel=source,
            target_channel=WORKFLOWS[source],
        )
        revision_list.append(revisions)
        if cmd:
            release_cmds.append(cmd)

    for charm in OVN_CHARMS:
        cmd, revisions = release_command(
            charm,
            track=TRACKS[release]["ovn"],
            source_channel=source,
            target_channel=WORKFLOWS[source],
        )
        revision_list.append(revisions)
        if cmd:
            release_cmds.append(cmd)

    for charm in CONSUL_CHARMS:
        if "consul" in TRACKS[release]:
            cmd, revisions = release_command(
                charm,
                track=TRACKS[release]["consul"],
                source_channel=source,
                target_channel=WORKFLOWS[source],
            )
            revision_list.append(revisions)
            if cmd:
                release_cmds.append(cmd)

    for charm in ["rabbitmq-k8s", "designate-bind-k8s"]:
        cmd, revisions = release_command(
            charm,
            track=TRACKS[release][charm],
            source_channel=source,
            target_channel=WORKFLOWS[source],
        )
        revision_list.append(revisions)
        if cmd:
            release_cmds.append(cmd)

    # Promote OpenStack snaps
    for snap in OPENSTACK_SNAPS:
        cmd, revisions = snap_promote_command(
            snap,
            track=TRACKS[release]["openstack"],
            source_channel=source,
            target_channel=WORKFLOWS[source],
        )
        revision_list.append(revisions)
        if cmd:
            release_cmds.append(cmd)

    # Promote Consul snaps
    for snap in CONSUL_SNAPS:
        if "consul" in TRACKS[release]:
            cmd, revisions = snap_promote_command(
                snap,
                track=TRACKS[release]["consul"],
                source_channel=source,
                target_channel=WORKFLOWS[source],
            )
            revision_list.append(revisions)
            if cmd:
                release_cmds.append(cmd)

    for rev in revision_list:
        current = rev["target_revision"]
        rev["promoted_revision"] = (
            rev["source_revision"] if rev["promoted"] else current
        )

    dependent_charms = []
    for app in DEPENDENT_CHARMS:
        track = dependent_track(app, release)
        if track is None:
            print(
                f"Skipping dependent charm {app}:"
                f" no track for release {release}"
            )
            continue
        channel = f"{track}/stable"
        print(f"Checking dependent charm {app}: {channel}")
        try:
            stable_revision = charm_stable_revision(app, track)
        except subprocess.CalledProcessError as e:
            print(f"  Error getting charm info: {e.stderr or e}")
            stable_revision = None
        dependent_charms.append(
            {
                "app": app,
                "channel": channel,
                "stable_revision": stable_revision,
            }
        )

    dependent_snaps = []
    for snap in DEPENDENT_SNAPS:
        track = dependent_track(snap, release)
        if track is None:
            print(
                f"Skipping dependent snap {snap}:"
                f" no track for release {release}"
            )
            continue
        channel = f"{track}/stable"
        print(f"Checking dependent snap {snap}: {channel}")
        try:
            stable_revision = snap_stable_revision(snap, track)
        except subprocess.CalledProcessError as e:
            print(f"  Error getting snap info: {e.stderr or e}")
            stable_revision = None
        dependent_snaps.append(
            {
                "app": snap,
                "channel": channel,
                "stable_revision": stable_revision,
            }
        )

    sections = [
        (
            "charms:",
            revision_entries(
                [r for r in revision_list if r["type"] == "charm"]
            ),
        ),
        (
            "snaps:",
            revision_entries(
                [r for r in revision_list if r["type"] == "snap"]
            ),
        ),
        ("dependent_charms:", dependent_charms),
        ("dependent_snaps:", dependent_snaps),
    ]

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    base_name = f"{release}-{source}-to-{WORKFLOWS[source]}-{timestamp}"
    if output_format in ("table", "both"):
        filename = f"{base_name}.txt"
        table = (
            f"Revision list (channel {WORKFLOWS[source]}:"
            " current -> promoted):\n" + render_table(sections)
        )
        Path(filename).write_text(table + "\n")
        print(f"Revision table written to {filename}")
    if output_format in ("yaml", "both"):
        filename = f"{base_name}.yaml"
        Path(filename).write_text(render_yaml(sections) + "\n")
        print(f"Revision yaml written to {filename}")

    for cmd in release_cmds:
        pcmd = " ".join(cmd)
        print(f"Running cmd: {pcmd}")
        if not dry_run:
            # For snapcraft promote commands, allow interactive input
            if cmd[0] == "snapcraft" and cmd[1] == "promote":
                process = subprocess.run(cmd, check=True)
            else:
                process = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True,
                    env=charmcraft_env(),
                )
                print(process.stdout)
