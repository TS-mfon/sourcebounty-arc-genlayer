// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Script} from "forge-std/Script.sol";
import {SourceBountyEscrow} from "../src/SourceBountyEscrow.sol";

contract Deploy is Script {
    function run() external returns (SourceBountyEscrow escrow) {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        address owner = vm.envAddress("OWNER");
        address relaySigner = vm.envAddress("RELAY_SIGNER");
        vm.startBroadcast(deployerKey);
        escrow = new SourceBountyEscrow(owner, relaySigner);
        vm.stopBroadcast();
    }
}
