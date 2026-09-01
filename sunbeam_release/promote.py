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
import subprocess
from typing import (
    Union,
    List,
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

CONSUL_CHARMS =[
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
    },
    "epoxy": {
        "openstack": "2025.1",
        "ovn": "25.03",
        "rabbitmq-k8s": "3.12",
        "designate-bind-k8s": "9",
        "consul": "1.19",
    },
    "gazpacho": {
        "openstack": "2026.1",
        "ovn": "26.03",
        "rabbitmq-k8s": "3.12",
        "designate-bind-k8s": "9",
        "consul": "1.19",
    }
}


def charm_metadata(app: str) -> dict:
    """Retrieve metadata about a specific charm."""
    cmd = ["charmcraft", "status", app, "--format", "json"]
    process = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(process.stdout.strip())


def snap_metadata(snap: str) -> dict:
    """Retrieve metadata about a specific snap."""
    cmd = ["snap", "info", snap]
    process = subprocess.run(cmd, capture_output=True, text=True, check=True)
    output = process.stdout.strip()

    # Parse the channels section
    channels = {}
    in_channels_section = False

    for line in output.split('\n'):
        if line.startswith('channels:'):
            in_channels_section = True
            continue

        if in_channels_section:
            # Stop if we hit an empty line or a new section
            if not line.strip() or (line and not line.startswith(' ')):
                break

            # Parse channel line format: "  track/risk:  version date (revision) size -"
            parts = line.strip().split()
            if len(parts) >= 2:
                channel = parts[0].rstrip(':')
                if parts[1] == '--':
                    # Channel is empty
                    channels[channel] = None
                elif parts[1] == '^':
                    # Channel is tracking the channel above
                    channels[channel] = 'tracking'
                else:
                    # Extract revision from parentheses
                    revision = None
                    for part in parts:
                        if part.startswith('(') and part.endswith(')'):
                            revision = part.strip('()')
                            break
                    channels[channel] = {
                        'version': parts[1],
                        'revision': revision
                    }

    return {'channels': channels}


def release_command(
    app: str,
    track: str,
    source_channel: str,
    target_channel: str,
    base_channels: List[str] = ["22.04", "24.04"],
    base_archs: List[str] = ["amd64"],
) -> Union[str, None]:
    """Generate a charmcraft release command to promote between tracks."""
    release_cmd = None
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
                        break

    return release_cmd


def snap_promote_command(
    snap: str,
    track: str,
    source_channel: str,
    target_channel: str,
) -> Union[str, None]:
    """Generate a snapcraft promote command to promote between channels."""
    from_channel = f"{track}/{source_channel}"
    to_channel = f"{track}/{target_channel}"

    print(f"Checking snap {snap}: {from_channel}->{to_channel}")

    try:
        snap_info = snap_metadata(snap)
        channels = snap_info.get('channels', {})

        source_info = channels.get(from_channel)
        target_info = channels.get(to_channel)

        # Check if source channel exists and has content
        if source_info is None:
            print(f"  Source channel {from_channel} is empty, skipping")
            return None

        if source_info == 'tracking':
            print(f"  Source channel {from_channel} is tracking, skipping")
            return None

        # Check if target channel exists
        if target_info is None:
            print(f"  Target channel {to_channel} is empty, will promote")
        elif target_info == 'tracking':
            print(f"  Target channel {to_channel} is tracking, will promote")
        elif isinstance(source_info, dict) and isinstance(target_info, dict):
            # Compare revisions
            if source_info.get('revision') == target_info.get('revision'):
                print(f"  Source and target revision match ({source_info.get('revision')}), skipping")
                return None
            else:
                print(f"  Source revision {source_info.get('revision')} != target revision {target_info.get('revision')}, will promote")

        promote_cmd = [
            "snapcraft",
            "promote",
            snap,
            "--from-channel",
            from_channel,
            "--to-channel",
            to_channel,
        ]

        return promote_cmd

    except subprocess.CalledProcessError as e:
        print(f"  Error getting snap info: {e}")
        return None


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
def promote(source: str, release: str, dry_run: bool) -> None:
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

    for charm in OPENSTACK_CHARMS:
        cmd = release_command(
            charm,
            track=TRACKS[release]["openstack"],
            source_channel=source,
            target_channel=WORKFLOWS[source],
        )
        if cmd:
            release_cmds.append(cmd)

    for charm in OVN_CHARMS:
        cmd = release_command(
            charm,
            track=TRACKS[release]["ovn"],
            source_channel=source,
            target_channel=WORKFLOWS[source],
        )
        if cmd:
            release_cmds.append(cmd)

    for charm in CONSUL_CHARMS:
        if "consul" in TRACKS[release]:
            cmd = release_command(
                charm,
                track=TRACKS[release]["consul"],
                source_channel=source,
                target_channel=WORKFLOWS[source],
            )
            if cmd:
                release_cmds.append(cmd)

    for charm in ["rabbitmq-k8s", "designate-bind-k8s"]:
        cmd = release_command(
            charm,
            track=TRACKS[release][charm],
            source_channel=source,
            target_channel=WORKFLOWS[source],
        )
        if cmd:
            release_cmds.append(cmd)

    # Promote OpenStack snaps
    for snap in OPENSTACK_SNAPS:
        cmd = snap_promote_command(
            snap,
            track=TRACKS[release]["openstack"],
            source_channel=source,
            target_channel=WORKFLOWS[source],
        )
        if cmd:
            release_cmds.append(cmd)

    # Promote Consul snaps
    for snap in CONSUL_SNAPS:
        if "consul" in TRACKS[release]:
            cmd = snap_promote_command(
                snap,
                track=TRACKS[release]["consul"],
                source_channel=source,
                target_channel=WORKFLOWS[source],
            )
            if cmd:
                release_cmds.append(cmd)

    for cmd in release_cmds:
        pcmd = " ".join(cmd)
        print(f"Running cmd: {pcmd}")
        if not dry_run:
            # For snapcraft promote commands, allow interactive input
            if cmd[0] == "snapcraft" and cmd[1] == "promote":
                process = subprocess.run(cmd, check=True)
            else:
                process = subprocess.run(
                    cmd, capture_output=True, text=True, check=True
                )
                print(process.stdout)
