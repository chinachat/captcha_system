<?php
/**
 * 卸载时清理配置。
 *
 * @package Captcha_Guard
 */

defined( 'WP_UNINSTALL_PLUGIN' ) || exit;

delete_option( 'captcha_guard_options' );
