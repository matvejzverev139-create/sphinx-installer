package com.qwermix.autototem;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.world.inventory.ClickType;
import net.minecraft.world.item.Items;

/**
 * Если левая рука (offhand) пуста — например, тотем только что сработал —
 * берём тотем из инвентаря и кладём его в левую руку.
 */
public class AutoTotemClient implements ClientModInitializer {
	/** "Кнопка" 40 в клике SWAP означает обмен со слотом левой руки. */
	private static final int OFFHAND_SWAP_BUTTON = 40;
	/** Пауза между попытками (тики), чтобы сервер успел ответить. */
	private static final int COOLDOWN_TICKS = 4;

	private int cooldown = 0;

	@Override
	public void onInitializeClient() {
		ClientTickEvents.END_CLIENT_TICK.register(this::tick);
	}

	private void tick(Minecraft mc) {
		LocalPlayer player = mc.player;
		if (player == null || mc.gameMode == null || mc.level == null) return;
		if (!player.isAlive() || player.isSpectator()) return;
		// Открыт сундук/верстак и т.п. — пакет для инвентаря игрока сервер проигнорирует.
		if (player.containerMenu != player.inventoryMenu) return;

		if (cooldown > 0) {
			cooldown--;
			return;
		}
		if (!player.getOffhandItem().isEmpty()) return;

		int slot = findTotem(player);
		if (slot < 0) return;

		// Номера слотов в меню инвентаря: хотбар 0-8 -> 36-44, основной 9-35 -> 9-35.
		int menuSlot = slot < 9 ? slot + 36 : slot;
		mc.gameMode.handleInventoryMouseClick(
				player.inventoryMenu.containerId, menuSlot, OFFHAND_SWAP_BUTTON, ClickType.SWAP, player);
		cooldown = COOLDOWN_TICKS;
	}

	/** Сначала ищем в основном инвентаре, потом в хотбаре. Возвращает индекс в инвентаре или -1. */
	private static int findTotem(LocalPlayer player) {
		for (int i = 9; i < 36; i++) {
			if (player.getInventory().getItem(i).is(Items.TOTEM_OF_UNDYING)) return i;
		}
		for (int i = 0; i < 9; i++) {
			if (player.getInventory().getItem(i).is(Items.TOTEM_OF_UNDYING)) return i;
		}
		return -1;
	}
}
