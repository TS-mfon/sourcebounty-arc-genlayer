// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Test} from "forge-std/Test.sol";
import {SourceBountyEscrow} from "../src/SourceBountyEscrow.sol";

contract SourceBountyEscrowTest is Test {
    SourceBountyEscrow escrow;
    address owner = address(0xA11CE);
    address relay = address(0xBEEF);
    address creator = address(0xB0B);
    address responder = address(0xCAFE);

    function setUp() public {
        escrow = new SourceBountyEscrow(owner, relay);
        vm.deal(creator, 1000 ether);
    }

    function _fundedAnsweredBounty() internal returns (uint256 bountyId) {
        vm.prank(creator);
        bountyId = escrow.createBounty(keccak256("question"), 10 ether, uint64(block.timestamp + 1 days));
        vm.prank(creator);
        escrow.fundBounty{value: 10 ether}(bountyId);
        vm.prank(responder);
        escrow.submitAnswer(bountyId, keccak256("answer"));
    }

    function testAcceptedBountyRewardsResponder() public {
        uint256 bountyId = _fundedAnsweredBounty();
        uint256 beforeBalance = responder.balance;
        vm.prank(relay);
        escrow.recordVerdict(bountyId, true, keccak256("verdict"));
        escrow.releaseReward(bountyId);
        assertEq(responder.balance - beforeBalance, 10 ether);
    }

    function testRejectedBountyRefundsCreator() public {
        uint256 bountyId = _fundedAnsweredBounty();
        uint256 beforeBalance = creator.balance;
        vm.prank(relay);
        escrow.recordVerdict(bountyId, false, keccak256("verdict"));
        vm.prank(creator);
        escrow.refundCreator(bountyId);
        assertEq(creator.balance - beforeBalance, 10 ether);
    }

    function testWrongRelayCannotRecordVerdict() public {
        uint256 bountyId = _fundedAnsweredBounty();
        vm.expectRevert(SourceBountyEscrow.NotRelay.selector);
        escrow.recordVerdict(bountyId, true, keccak256("verdict"));
    }

    function testCannotFundWrongAmount() public {
        vm.prank(creator);
        uint256 bountyId = escrow.createBounty(keccak256("question"), 10 ether, uint64(block.timestamp + 1 days));
        vm.expectRevert(SourceBountyEscrow.InvalidAmount.selector);
        vm.prank(creator);
        escrow.fundBounty{value: 9 ether}(bountyId);
    }
}
